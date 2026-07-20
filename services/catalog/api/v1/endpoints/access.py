"""Access-review endpoints (#51): who holds which ``can_*`` action on a table or namespace.

``POST …/access/list`` answers the standing-access question the #41 audit trail cannot ("who *can*
read this?", not "who *did*"): for every ``can_*`` action the compiled model defines on the type, it
asks OpenFGA ListUsers — which expands role assignees, team members, and the parent cascade, so the
answer is effective access, not just direct tuples. The relation set comes from the model the app
actually loads (never a hand-kept list), so a model edit is reflected here automatically and
``test_fga_model_contract`` proves every queried pair exists.

Owner-tier gated by the router-level ``authorize`` (``access/list`` maps to ``can_drop`` /
``can_delete`` — an enumeration reveals principals, so it clears the same bar as destroying the
object); the gate audits the authz decision, and the endpoint additionally emits a dedicated
``access_review`` audit event (the disclosure itself, distinguishable from an actual drop — the same
two-layer pattern as credential vending). Fail-closed: an OpenFGA outage is a 503, never an empty
grant list that reads as "nobody has access".

Two properties of "effective access" are accepted by design and worth knowing when reading a review:
the expansion follows the parent cascade, so a leaf-table owner sees individual grantees who hold
access only via namespace/warehouse/project team or role grants (within-tenant upward visibility —
the cascade never crosses projects); and OpenFGA's ListUsers has no pagination, so a relation held
by more subjects than the server's ``listUsersMaxResults`` cap returns a partial list (the wrapper
logs a warning when a result looks capped).
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from common import fga
from common.audit import FAILURE, SUCCESS, audit
from fastapi import APIRouter, Request
from lance_namespace import ServiceUnavailableError, UnsupportedOperationError
from pydantic import BaseModel

from catalog.api.dependencies import SettingsDep
from catalog.api.security import CurrentToken
from catalog.core.config import Settings
from catalog.core.identifiers import parse_identifier

table_router = APIRouter(prefix="/v1/table", tags=["access"])
namespace_router = APIRouter(prefix="/v1/namespace", tags=["access"])


class RelationGrants(BaseModel):
    """One ``can_*`` action and every user subject holding it (``"*"`` = a public wildcard grant)."""

    relation: str
    users: list[str]


class AccessListResponse(BaseModel):
    object: str
    grants: list[RelationGrants]


class AccessCheckRequest(BaseModel):
    """A simulated authorization question — does ``user`` hold ``relation`` on this object? The
    ``user`` may be a bare subject (``alice``, taken as ``user:alice``) or a fully-qualified userset
    (``role:project_admin``, ``team:acme#member``)."""

    user: str
    relation: str


class AccessCheckResponse(BaseModel):
    object: str
    user: str
    relation: str
    allowed: bool


@lru_cache
def _can_relations(fga_type: str) -> tuple[str, ...]:
    """Every ``can_*`` action the compiled model defines on ``fga_type``, sorted.

    Read from ``model.json`` (what the app loads) so the enumeration can never drift into a phantom
    relation — OpenFGA answers those with a 400 that fails closed to a 503 for every caller.
    """
    for td in fga.load_model()["type_definitions"]:
        if td["type"] == fga_type:
            return tuple(sorted(r for r in (td.get("relations") or {}) if r.startswith("can_")))
    return ()


async def _access_list(
    request: Request, settings: Settings, token: CurrentToken, fga_type: str, id: str
) -> AccessListResponse:
    if not settings.fga_enabled:
        raise UnsupportedOperationError("access review requires OpenFGA (this stack runs auth-off)")
    client = getattr(request.app.state, "fga", None)
    if client is None:  # the router gate already 503s this; kept so the endpoint is safe standalone
        raise ServiceUnavailableError("authorization service is not available")
    segments = parse_identifier(id, settings.delimiter)
    obj = f"{fga_type}:{fga.canonical_object_id(segments, delimiter=settings.delimiter)}"
    relations = _can_relations(fga_type)
    subject = token.sub if token else "anonymous"
    try:
        # TaskGroup, not gather: one failed relation cancels the siblings, so a degraded OpenFGA is
        # never hammered by up-to-nine orphaned retry loops after the request has already 503'd.
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(fga.list_users(client, relation=r, obj=obj)) for r in relations]
    except* ServiceUnavailableError as outage:
        # #41: the review FAILED mid-enumeration — without this, the gate's earlier allow would be
        # the only trace, indistinguishable from a completed disclosure.
        audit("access_review", FAILURE, subject=subject, resource=obj, reason="authz_unavailable")
        raise outage.exceptions[0] from None
    # #41 audit the actual ACL disclosure (who reviewed what) — the gate's can_drop/can_delete allow
    # alone would be byte-identical to a pending destructive op.
    audit("access_review", SUCCESS, subject=subject, resource=obj)
    return AccessListResponse(
        object=obj,
        grants=[
            RelationGrants(relation=relation, users=task.result())
            for relation, task in zip(relations, tasks, strict=True)
        ],
    )


@table_router.post("/{id}/access/list")
async def list_table_access(
    id: str, request: Request, settings: SettingsDep, token: CurrentToken
) -> AccessListResponse:
    """Effective access on the table, per ``can_*`` action — owner-gated by the router (``can_drop``)."""
    return await _access_list(request, settings, token, "table", id)


@namespace_router.post("/{id}/access/list")
async def list_namespace_access(
    id: str, request: Request, settings: SettingsDep, token: CurrentToken
) -> AccessListResponse:
    """Effective access on the namespace, per ``can_*`` action — owner-gated by the router
    (``can_delete``)."""
    return await _access_list(request, settings, token, "namespace", id)


async def _access_check(
    request: Request,
    settings: Settings,
    token: CurrentToken,
    fga_type: str,
    id: str,
    body: AccessCheckRequest,
) -> AccessCheckResponse:
    """The #68 playground's check primitive — a single ``(user, relation, object)`` OpenFGA Check,
    owner-gated identically to ``access/list`` (probing the graph is the same disclosure as enumerating
    it). Only relations the compiled model defines on ``fga_type`` may be probed, so an unknown relation
    is a clean 4xx here rather than a 400 that fails closed to a 503 for the caller."""
    if not settings.fga_enabled:
        raise UnsupportedOperationError("access simulation requires OpenFGA (this stack runs auth-off)")
    client = getattr(request.app.state, "fga", None)
    if client is None:  # the router gate already 503s this; kept so the endpoint is safe standalone
        raise ServiceUnavailableError("authorization service is not available")
    if body.relation not in _can_relations(fga_type):
        raise UnsupportedOperationError(f"{body.relation!r} is not a can_* relation on {fga_type}")
    segments = parse_identifier(id, settings.delimiter)
    obj = f"{fga_type}:{fga.canonical_object_id(segments, delimiter=settings.delimiter)}"
    subject = token.sub if token else "anonymous"
    # Resolve to a FULL subject: a bare id is a user (``user:<id>``); a qualified userset
    # (``role:…#member`` / ``team:…#member``) is passed through as-is. Then check with qualify=False so
    # fga.check sends it verbatim — otherwise its default ``user:`` prefix would double to ``user:user:…``
    # and every simulated Check would falsely deny (audit 2026-07-20 caught exactly this).
    user = body.user if ":" in body.user else f"user:{body.user}"
    try:
        allowed = await fga.check(client, user=user, relation=body.relation, obj=obj, qualify=False)
    except ServiceUnavailableError:
        audit("access_simulate", FAILURE, subject=subject, resource=obj, reason="authz_unavailable")
        raise
    # #41: the simulation IS an authz-graph disclosure (who probed what) — audit it distinctly from the
    # gate's owner allow, exactly like access_review / credential vending.
    audit("access_simulate", SUCCESS, subject=subject, resource=obj)
    return AccessCheckResponse(object=obj, user=user, relation=body.relation, allowed=allowed)


@table_router.post("/{id}/access/check")
async def check_table_access(
    id: str, request: Request, settings: SettingsDep, token: CurrentToken, body: AccessCheckRequest
) -> AccessCheckResponse:
    """Simulate 'does <user> hold <relation> on this table?' — owner-gated by the router (``can_drop``)."""
    return await _access_check(request, settings, token, "table", id, body)


@namespace_router.post("/{id}/access/check")
async def check_namespace_access(
    id: str, request: Request, settings: SettingsDep, token: CurrentToken, body: AccessCheckRequest
) -> AccessCheckResponse:
    """Simulate 'does <user> hold <relation> on this namespace?' — owner-gated (``can_delete``)."""
    return await _access_check(request, settings, token, "namespace", id, body)


# The v1 aggregator includes one ``router`` per module — the table + namespace routers are stitched here.
router = APIRouter()
router.include_router(table_router)
router.include_router(namespace_router)
