"""Maintenance-policy endpoints (#50): per-table/namespace overrides for the compaction sweep.

``POST …/policy/set`` and ``…/policy/delete`` are owner-tier (the router-level ``authorize`` maps them
to ``can_drop``/``can_delete`` — a retention policy authorizes destroying version history), and land on
the #41 audit trail through that same gate; ``…/policy/describe`` is a reader-tier metadata read. The
record stores both the logical id and the physical bucket-qualified path (resolved here), so the
compaction sweep enforces policies straight off the bucket with no catalog round-trip. Old-version
cleanup can never remove a tag-pinned version (Lance exempts tagged versions), so ``blessed`` and every
other promotion tag survive any policy.
"""

from __future__ import annotations

import logging

from common import fga
from common import maintenance_policies as policies
from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    DescribeTableRequest,
    InvalidInputError,
    NamespaceNotFoundError,
    TableNotFoundError,
)

from catalog.api.dependencies import NamespaceDep, SettingsDep
from catalog.core.identifiers import parse_identifier
from catalog.schemas import PolicyDeleteResponse, PolicyRequest, PolicyResponse
from catalog.services import native

log = logging.getLogger(__name__)

table_router = APIRouter(prefix="/v1/table", tags=["policy"])
namespace_router = APIRouter(prefix="/v1/namespace", tags=["policy"])


def _canonical(segments: list[str], delimiter: str) -> str:
    return fga.canonical_object_id(segments, delimiter=delimiter)


def _record(kind: str, canonical_id: str, path: str, body: PolicyRequest) -> dict[str, object]:
    return {"kind": kind, "id": canonical_id, "path": path, **body.model_dump()}


def _response(record: dict[str, object]) -> PolicyResponse:
    return PolicyResponse.model_validate(record)


def _sweep_path(location: str) -> str:
    """The sweep's match key for a storage location: bucket-qualified (``<bucket>/<path>``), so a
    policy can never govern a same-named path in a different tenant's bucket (the sweep spans the
    per-warehouse and multi-base buckets too)."""
    return location.removeprefix("s3://").rstrip("/")


@table_router.post("/{id}/policy/set", response_model_exclude_none=True)
async def set_table_policy(
    id: str, body: PolicyRequest, ns: NamespaceDep, settings: SettingsDep
) -> PolicyResponse:
    """Set (or replace) the table's maintenance policy — owner-gated by the router (``can_drop``)."""
    segments = parse_identifier(id, settings.delimiter)
    described = await run_in_threadpool(native.call, ns, "describe_table", DescribeTableRequest(id=segments))
    if described.location is None:
        raise TableNotFoundError(f"table {id!r} has no storage location to police")
    canonical = _canonical(segments, settings.delimiter)
    record = _record("table", canonical, _sweep_path(described.location), body)
    await run_in_threadpool(policies.put_policy, settings.registry_root, settings.storage_options(), record)
    log.info("maintenance_policy_set", extra={"kind": "table", "id": canonical})
    return _response(record)


@table_router.post("/{id}/policy/describe", response_model_exclude_none=True)
async def describe_table_policy(id: str, settings: SettingsDep) -> PolicyResponse:
    """The table's maintenance policy (reader-gated); 404 when none is set."""
    canonical = _canonical(parse_identifier(id, settings.delimiter), settings.delimiter)
    record = await run_in_threadpool(
        policies.get_policy, settings.registry_root, settings.storage_options(), "table", canonical
    )
    if record is None:
        raise TableNotFoundError(f"no maintenance policy set for table {id!r}")
    return _response(record)


@table_router.post("/{id}/policy/delete", response_model_exclude_none=True)
async def delete_table_policy(id: str, settings: SettingsDep) -> PolicyDeleteResponse:
    """Remove the table's maintenance policy (idempotent) — owner-gated by the router."""
    canonical = _canonical(parse_identifier(id, settings.delimiter), settings.delimiter)
    await run_in_threadpool(
        policies.delete_policy, settings.registry_root, settings.storage_options(), "table", canonical
    )
    log.info("maintenance_policy_deleted", extra={"kind": "table", "id": canonical})
    return PolicyDeleteResponse(status="deleted", kind="table", id=canonical)


@namespace_router.post("/{id}/policy/set", response_model_exclude_none=True)
async def set_namespace_policy(id: str, body: PolicyRequest, settings: SettingsDep) -> PolicyResponse:
    """Set (or replace) a namespace-level policy — applies to every dataset under the namespace's
    directory prefix unless a table policy overrides it. Owner-gated by the router (``can_delete``)."""
    segments = parse_identifier(id, settings.delimiter)
    if not segments:
        raise InvalidInputError("a policy needs a concrete namespace, not the root")
    canonical = _canonical(segments, settings.delimiter)
    # The dir backend maps a namespace to its directory prefix under the root bucket.
    prefix = _sweep_path(f"{settings.root.rstrip('/')}/{'/'.join(segments)}")
    record = _record("namespace", canonical, prefix, body)
    await run_in_threadpool(policies.put_policy, settings.registry_root, settings.storage_options(), record)
    log.info("maintenance_policy_set", extra={"kind": "namespace", "id": canonical})
    return _response(record)


@namespace_router.post("/{id}/policy/describe", response_model_exclude_none=True)
async def describe_namespace_policy(id: str, settings: SettingsDep) -> PolicyResponse:
    """The namespace's maintenance policy (reader-gated); 404 when none is set."""
    canonical = _canonical(parse_identifier(id, settings.delimiter), settings.delimiter)
    record = await run_in_threadpool(
        policies.get_policy, settings.registry_root, settings.storage_options(), "namespace", canonical
    )
    if record is None:
        raise NamespaceNotFoundError(f"no maintenance policy set for namespace {id!r}")
    return _response(record)


@namespace_router.post("/{id}/policy/delete", response_model_exclude_none=True)
async def delete_namespace_policy(id: str, settings: SettingsDep) -> PolicyDeleteResponse:
    """Remove the namespace's maintenance policy (idempotent) — owner-gated by the router."""
    canonical = _canonical(parse_identifier(id, settings.delimiter), settings.delimiter)
    await run_in_threadpool(
        policies.delete_policy, settings.registry_root, settings.storage_options(), "namespace", canonical
    )
    log.info("maintenance_policy_deleted", extra={"kind": "namespace", "id": canonical})
    return PolicyDeleteResponse(status="deleted", kind="namespace", id=canonical)


# The v1 aggregator includes one ``router`` per module — the table + namespace routers are stitched here.
router = APIRouter()
router.include_router(table_router)
router.include_router(namespace_router)
