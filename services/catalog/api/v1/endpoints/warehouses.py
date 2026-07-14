"""Admin control-plane endpoints: warehouse provisioning + warehouse-scoped namespaces (#3-A).

A *warehouse* = one physically separate S3 bucket owned by a project (the FGA model's catalog-root type).
These routes are the **control plane** the catalog lacked: an authorized project-admin provisions a bucket
at RUNTIME (not the static Helm `mc mb` loop) and creates namespaces bound to it, so tables under those
namespaces land in that warehouse's bucket — physically isolated from every other tenant's. Lakekeeper
parity for multi-tenancy; the routing itself (an unbound namespace → the shared default root) stays
backward-compatible.

Authorization is DELIBERATELY stronger than the data plane: warehouse-create gates on the project's
`can_create_warehouse` (= admin) — the model action that until now was defined but never enforced — not the
writer-tier create-on-parent that guards tables/namespaces.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from common import fga
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    CreateNamespaceRequest,
    CreateNamespaceResponse,
    InvalidInputError,
    NamespaceAlreadyExistsError,
    PermissionDeniedError,
    TableNotFoundError,
    UnsupportedOperationError,
)
from pydantic import BaseModel

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, SettingsDep, _namespace_for_root
from catalog.api.security import CurrentToken
from catalog.core.config import Settings
from catalog.core.identifiers import parse_identifier
from catalog.services import native, warehouses

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/warehouses", tags=["warehouse"])

# A bucket/warehouse id must be a DNS-safe S3 bucket name fragment (lowercase alnum + hyphen, 3-63 chars) —
# validated here so a malformed id can't produce an un-createable bucket or a path-traversing registry key.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


class CreateWarehouseRequest(BaseModel):
    id: str
    project: str
    bucket: str | None = None  # defaults to the id (a warehouse = one bucket)


class WarehouseResponse(BaseModel):
    id: str
    bucket: str
    root_uri: str
    project: str
    created_at: str | None = None


class CreateWarehouseNamespaceRequest(BaseModel):
    namespace: str  # a single TOP-LEVEL namespace name to create in + bind to this warehouse


def _require_enabled(settings: Settings) -> None:
    # A DOMAIN error, not a raw HTTPException: this module was the only endpoint module bypassing the
    # RFC 9457 problem+json handler, so its errors came back shaped differently from every other route in
    # the API (audit 2026-07-14). UnsupportedOperationError maps to the spec-correct 501.
    if not settings.warehouses_enabled:
        raise UnsupportedOperationError("warehouses are disabled (set LANCE_WAREHOUSES_ENABLED)")


def _validate_id(value: str, *, what: str) -> str:
    if not _ID_RE.match(value):
        raise InvalidInputError(f"invalid {what} {value!r}: must match {_ID_RE.pattern}")
    return value


@router.post("", response_model_exclude_none=True)
async def create_warehouse(
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    body: CreateWarehouseRequest,
) -> WarehouseResponse:
    """Provision a warehouse: create its physical bucket + register it + seed FGA. Admin-gated.

    Order (fail-closed): authorize FIRST (``can_create_warehouse`` on the project), THEN provision the
    bucket (idempotent), write the registry record, and grant the caller ``owner`` on ``warehouse:<id>``
    with a ``parent`` edge to the project. A re-run with the same id is idempotent (bucket + record both
    overwrite-safe)."""
    _require_enabled(settings)
    warehouse_id = _validate_id(body.id, what="warehouse id")
    project = _validate_id(body.project, what="project id")
    bucket = _validate_id(body.bucket or body.id, what="bucket name")
    await fga_deps.require_can_create_warehouse(client, settings, token, project=project)

    so = settings.storage_options()
    # Cross-tenant takeover guard: `can_create_warehouse` gates on the caller-named `project`, so an admin of
    # ANY project could otherwise re-POST an EXISTING warehouse id under their own project — the seed ADDS
    # `warehouse:<id> project project:<theirs>` alongside the original owner's tuples, making their project's
    # members readers of the victim's warehouse + every table under it (routing still points at the same
    # bucket → full cross-tenant disclosure). Reject a collision with a warehouse owned by another project.
    # A same-project re-create stays idempotent (the partial-failure retry path below relies on it).
    existing = await run_in_threadpool(warehouses.get_warehouse, settings.registry_root, so, warehouse_id)
    if existing is not None and existing.get("project") != project:
        raise NamespaceAlreadyExistsError(
            f"warehouse {warehouse_id!r} is already registered to another project"
        )

    root_uri = f"s3://{bucket}"
    await run_in_threadpool(warehouses.provision_bucket, bucket, so)
    record = {
        "id": warehouse_id,
        "bucket": bucket,
        "root_uri": root_uri,
        "project": project,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await run_in_threadpool(warehouses.put_warehouse, settings.registry_root, so, record)
    await fga_deps.seed_warehouse(client, settings, token, warehouse_id=warehouse_id, project=project)
    log.info("warehouse_created", extra={"warehouse": warehouse_id, "bucket": bucket, "project": project})
    return WarehouseResponse(**record)


@router.get("", response_model_exclude_none=True)
async def list_warehouses(
    settings: SettingsDep, token: CurrentToken, client: FgaClientDep
) -> list[WarehouseResponse]:
    """Every warehouse the caller can read. Governed like the metadata feeds: with FGA on, filtered to the
    warehouses the caller has ``can_get_metadata`` on (never discloses another tenant's bucket names)."""
    _require_enabled(settings)
    records = await run_in_threadpool(
        warehouses.list_warehouses, settings.registry_root, settings.storage_options()
    )
    if settings.fga_enabled and client is not None and token is not None:
        allowed = set(
            await fga.list_objects(
                client, user=token.sub, relation="can_get_metadata", object_type="warehouse"
            )
        )
        records = [r for r in records if f"warehouse:{r['id']}" in allowed]
    return [WarehouseResponse(**r) for r in records]


@router.get("/{warehouse_id}", response_model_exclude_none=True)
async def get_warehouse(
    warehouse_id: str, settings: SettingsDep, token: CurrentToken, client: FgaClientDep
) -> WarehouseResponse:
    """One warehouse record — reader-gated on ``warehouse:<id>`` (fail-closed on an OpenFGA outage)."""
    _require_enabled(settings)
    if (
        settings.fga_enabled
        and client is not None
        and token is not None
        and not await fga.check(
            client, user=token.sub, relation="can_get_metadata", obj=f"warehouse:{warehouse_id}"
        )
    ):
        raise PermissionDeniedError(f"can_get_metadata required on warehouse:{warehouse_id}")
    record = await run_in_threadpool(
        warehouses.get_warehouse, settings.registry_root, settings.storage_options(), warehouse_id
    )
    if record is None:
        raise TableNotFoundError(f"warehouse not found: {warehouse_id}")
    return WarehouseResponse(**record)


@router.post("/{warehouse_id}/namespaces", response_model_exclude_none=True)
async def create_warehouse_namespace(
    warehouse_id: str,
    request: Request,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    body: CreateWarehouseNamespaceRequest,
) -> CreateNamespaceResponse:
    """Create a top-level namespace INSIDE this warehouse's bucket and bind it, so all its tables route
    there (#3-A physical isolation). Gated on ``can_create_namespace`` (writer) on ``warehouse:<id>``.

    The namespace is created via the warehouse's bucket-rooted connection (not the default), the binding is
    persisted + cached (so subsequent table ops resolve without a registry read), and FGA is seeded with the
    namespace's ``parent`` edge pointing at the warehouse — so the owner's grant cascades into the tables."""
    _require_enabled(settings)
    ns_name = _validate_id(body.namespace, what="namespace name")
    if (
        settings.fga_enabled
        and client is not None
        and token is not None
        and not await fga.check(
            client, user=token.sub, relation="can_create_namespace", obj=f"warehouse:{warehouse_id}"
        )
    ):
        raise PermissionDeniedError(f"can_create_namespace required on warehouse:{warehouse_id}")
    record = await run_in_threadpool(
        warehouses.get_warehouse, settings.registry_root, settings.storage_options(), warehouse_id
    )
    if record is None:
        raise TableNotFoundError(f"warehouse not found: {warehouse_id}")
    root_uri = record["root_uri"]

    # Binding is WRITE-ONCE: reject re-binding a top-level namespace already bound to a DIFFERENT warehouse.
    # Without this, tenant B could bind tenant A's namespace name → the binding object is overwritten, A's
    # existing tables become unreachable (routing sends the id to B's bucket where they don't exist) and A's
    # new writes physically land in B's bucket; positive-cached-forever routing makes replicas disagree.
    existing_binding = await run_in_threadpool(
        warehouses.warehouse_for_namespace, settings.registry_root, settings.storage_options(), ns_name
    )
    if existing_binding is not None and existing_binding != root_uri:
        raise NamespaceAlreadyExistsError(f"namespace {ns_name!r} is already bound to another warehouse")

    ns_conn = _namespace_for_root(request, settings, root_uri)
    segments = parse_identifier(ns_name, settings.delimiter)
    req = CreateNamespaceRequest(id=segments)
    response: CreateNamespaceResponse = await run_in_threadpool(native.call, ns_conn, "create_namespace", req)
    # Persist + cache the binding BEFORE returning, so the very next table-create routes to this bucket.
    await run_in_threadpool(
        warehouses.bind_namespace,
        settings.registry_root,
        settings.storage_options(),
        ns_name,
        warehouse_id,
        root_uri,
    )
    request.app.state.warehouse_binding_cache[ns_name] = root_uri
    # Seed FGA: owner on the namespace + parent edge to the WAREHOUSE (not the shared root), so the
    # concentric cascade project → warehouse → namespace → table reaches the tables created here.
    if settings.fga_enabled and token is not None and client is not None:
        await fga.grant_on_create(
            client,
            user_sub=token.sub,
            resource="namespace",
            obj_id=fga.canonical_object_id(segments, delimiter=settings.delimiter),
            parent_object=f"warehouse:{warehouse_id}",
        )
    log.info("warehouse_namespace_created", extra={"warehouse": warehouse_id, "namespace": ns_name})
    return response
