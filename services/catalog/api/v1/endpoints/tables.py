"""Table metadata + lifecycle endpoints (no data plane)."""

from __future__ import annotations

from typing import Annotated

from common import fga
from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    DeclareTableRequest,
    DeclareTableResponse,
    DeregisterTableRequest,
    DeregisterTableResponse,
    DescribeTableRequest,
    DescribeTableResponse,
    DropTableRequest,
    DropTableResponse,
    GetTableStatsRequest,
    GetTableStatsResponse,
    GetTableTagVersionRequest,
    InvalidInputError,
    ListTablesRequest,
    ListTablesResponse,
    RegisterTableRequest,
    RegisterTableResponse,
    RenameTableRequest,
    RenameTableResponse,
    RestoreTableRequest,
    RestoreTableResponse,
    TableExistsRequest,
)

from catalog.api import fga_deps, lineage_deps
from catalog.api.dependencies import (
    FgaClientDep,
    LineageEmitterDep,
    NamespaceDep,
    SettingsDep,
    StorageOptionsDep,
)
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.core.lineage_emit import (
    DECLARE_TABLE,
    DEREGISTER_TABLE,
    DROP_TABLE,
    REGISTER_TABLE,
    RESTORE_TABLE,
    emit_write_event,
)
from catalog.services import dataplane, native

router = APIRouter(prefix="/v1/table", tags=["table"])


@router.get("", response_model_exclude_none=True)
async def list_all_tables(
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    page_token: str | None = None,
    limit: int | None = None,
    include_declared: bool = True,
) -> ListTablesResponse:
    """List every table in the namespace via ``list_all_tables``; when FGA is on,
    filter the result down to the tables the caller can ``can_read_data``.
    ``include_declared=false`` drops declared-only tables (reserved, no storage yet)."""
    req = ListTablesRequest(id=[], page_token=page_token, limit=limit, include_declared=include_declared)
    response: ListTablesResponse = await run_in_threadpool(native.call, ns, "list_all_tables", req)
    # When FGA is on and the caller is known, return only the tables they can read.
    # Each table name is the canonical id suffix, matching ``table:<name>`` from list_objects.
    if settings.fga_enabled and token is not None and client is not None:
        allowed = set(
            await fga.list_objects(client, user=token.sub, relation="can_read_data", object_type="table")
        )
        response.tables = [name for name in response.tables if f"table:{name}" in allowed]
    return response


@router.post("/{id}/declare", response_model_exclude_none=True)
async def declare_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    body: DeclareTableRequest | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> DeclareTableResponse:
    """Declare a new (empty) table at ``id`` via ``declare_table``, then seed the caller's FGA ownership
    and emit a versionless DECLARE_TABLE marker (the table's first provenance — who reserved it + where)."""
    segments = parse_identifier(id, settings.delimiter)
    req = body or DeclareTableRequest()
    req.id = segments
    response: DeclareTableResponse = await run_in_threadpool(native.call, ns, "declare_table", req)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    # Versionless (no data yet): records who declared it + the reserved location, and keys the CREATED edge
    # (declare_table ∈ lineage _CREATE_OPS). Reconcile fills the real version once data lands at the URI.
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=None,
        operation=DECLARE_TABLE,
        authorization=authorization,
        source_uri=response.location,
    )
    return response


@router.post("/{id}/describe", response_model_exclude_none=True)
def describe_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    with_table_uri: bool | None = None,
    load_detailed_metadata: bool | None = None,
    check_declared: bool | None = None,
    version: int | None = None,
    tag: str | None = None,
) -> DescribeTableResponse:
    """Describe the table at ``id`` (schema / uri / detailed metadata) via ``describe_table``,
    optionally at ``?version=N`` or ``?tag=<name>`` (spec 0.9: mutually exclusive).

    ``tag`` is resolved to its version HERE via the dataplane's tag store: the native backend at
    pylance 8.0.0 silently IGNORES a describe-request ``tag`` (probed 2026-07-10 — a nonexistent tag
    described the LATEST version with no error), so forwarding it would lie; the catalog resolves
    (404 on an unknown tag, like ``/tags/version``) and describes at the resolved version instead.
    """
    segments = parse_identifier(id, settings.delimiter)
    if tag is not None:
        if version is not None:
            raise InvalidInputError("`tag` cannot be used together with `version` (spec 0.9)")
        resolved = dataplane.get_tag_version(ns, so, GetTableTagVersionRequest(id=segments, tag=tag))
        version = resolved.version
    req = DescribeTableRequest(
        id=segments,
        with_table_uri=with_table_uri,
        load_detailed_metadata=load_detailed_metadata,
        check_declared=check_declared,
        version=version,
    )
    return native.call(ns, "describe_table", req)


@router.post("/{id}/exists", status_code=200)
def table_exists(id: str, ns: NamespaceDep, settings: SettingsDep) -> None:
    """Check the table at ``id`` exists via ``table_exists`` — 200 if present (spec 0.9), else error."""
    native.call(ns, "table_exists", TableExistsRequest(id=parse_identifier(id, settings.delimiter)))


@router.post("/{id}/drop", response_model_exclude_none=True)
async def drop_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    token: CurrentToken,
    authorization: Annotated[str | None, Header()] = None,
) -> DropTableResponse:
    """Drop the table at ``id`` via ``drop_table``, then revoke its FGA tuples and
    emit a best-effort ``drop_table`` lineage event."""
    segments = parse_identifier(id, settings.delimiter)
    response: DropTableResponse = await run_in_threadpool(
        native.call, ns, "drop_table", DropTableRequest(id=segments)
    )
    # Record the drop as best-effort lineage — provenance of the deletion (the dataset node persists in the
    # graph, named a `drop_table` run). Inline-awaited (NOT BackgroundTasks) → reaches the durable
    # Dapr/JetStream transport before the response; best-effort, so it never fails the drop. Emitted BEFORE
    # the revoke: on the http transport the caller's bearer authorizes ingest against their (still-live)
    # write grant — revoking first would 403 the very event that records who dropped the table.
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=None,
        operation=DROP_TABLE,
        authorization=authorization,
    )
    # Revoke the table's FGA tuples so a later table reusing this id can't inherit stale grants.
    await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
    return response


@router.post("/{id}/deregister", response_model_exclude_none=True)
async def deregister_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    token: CurrentToken,
    authorization: Annotated[str | None, Header()] = None,
) -> DeregisterTableResponse:
    """Deregister the table at ``id`` (detach it without deleting data) via lance_namespace
    ``deregister_table``, then revoke its FGA ownership and emit a best-effort ``deregister_table`` marker."""
    segments = parse_identifier(id, settings.delimiter)
    response: DeregisterTableResponse = await run_in_threadpool(
        native.call, ns, "deregister_table", DeregisterTableRequest(id=segments)
    )
    # Record the detach as best-effort lineage — asymmetric with drop (which deletes data), deregister
    # only detaches, so without this marker the Dataset node looks like a still-live, never-touched table.
    # Versionless (no data was written), inline-awaited so it reaches the durable transport before the
    # reply. Emitted BEFORE the revoke: on the http transport the caller's bearer authorizes ingest against
    # their (still-live) write grant — revoking first would 403 the very marker this endpoint exists to
    # record, and the graph would keep showing the table as live.
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=None,
        operation=DEREGISTER_TABLE,
        authorization=authorization,
    )
    await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
    return response


@router.post("/{id}/register", response_model_exclude_none=True)
async def register_table(
    id: str,
    body: RegisterTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> RegisterTableResponse:
    """Register an existing table location at ``id`` via ``register_table``, then seed the caller's FGA
    ownership and emit a REGISTER_TABLE marker (who attached it + where)."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: RegisterTableResponse = await run_in_threadpool(native.call, ns, "register_table", body)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    # Versionless + source_uri=the attached location, keying the CREATED edge (register_table ∈ _CREATE_OPS).
    # The registered table already holds data at some version; we don't reopen a possibly-external location on
    # the request path (a reopen failure must never fail an already-committed register) — #23 reconcile reads
    # that source_uri and back-fills the real on-disk version (UNTRACKED → in-sync).
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=None,
        operation=REGISTER_TABLE,
        authorization=authorization,
        source_uri=response.location,
    )
    return response


@router.post("/{id}/rename", response_model_exclude_none=True)
async def rename_table(
    id: str,
    body: RenameTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
) -> RenameTableResponse:
    """Rename the table at ``id`` to its new id via ``rename_table``, then revoke
    the source id's FGA tuples and seed ownership on the destination id.

    No lineage is emitted: the ``dir`` namespace backend returns 501 for ``rename_table`` (unsupported), so a
    rename can't happen on the shipped stack — provenance can't be lost on an op that never runs. If a
    rename-supporting backend is adopted, emit dest←source lineage here (see todo_fable §11)."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    # Rename mints a new table identifier under ``new_namespace_id`` (defaulting to the source's parent
    # namespace, i.e. all source segments but the last) + ``new_table_name``.
    dest_parent = list(body.new_namespace_id) if body.new_namespace_id else segments[:-1]
    new_segments = [*dest_parent, body.new_table_name]
    # Renaming INTO a namespace is a create in that namespace: authorize can_create_table on the DESTINATION
    # parent BEFORE the (destructive, relocating) native rename — else a source-table owner could plant their
    # table into a namespace/tenant they have no create rights on. (authorize already gated can_drop on the
    # source at owner tier.)
    await fga_deps.require_create_on_parent(client, settings, token, resource="table", segments=new_segments)
    response: RenameTableResponse = await run_in_threadpool(native.call, ns, "rename_table", body)
    # Revoke the SOURCE id's tuples (it no longer names a table) then seed the destination — so no
    # stale grant survives under the old id and the caller keeps ownership under the new one.
    await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=new_segments)
    return response


@router.post("/{id}/restore", response_model_exclude_none=True)
async def restore_table(
    id: str,
    body: RestoreTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> RestoreTableResponse:
    """Restore the table at ``id`` to a prior version via ``restore_table``; emits a RESTORE_TABLE event at
    the NEW current version (restore mints a fresh version pointing at the restored data)."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: RestoreTableResponse = await run_in_threadpool(native.call, ns, "restore_table", body)
    # The response carries only a transaction_id — the shared trailer reads the new current version + its
    # schema off one reopen (best-effort: a readback failure never fails the already-committed restore).
    await lineage_deps.emit_measured_write(
        emitter,
        segments,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        operation=RESTORE_TABLE,
        authorization=authorization,
    )
    return response


@router.post("/{id}/stats", response_model_exclude_none=True)
def get_table_stats(id: str, ns: NamespaceDep, settings: SettingsDep) -> GetTableStatsResponse:
    """Return storage/row statistics for the table at ``id`` via ``get_table_stats``."""
    req = GetTableStatsRequest(id=parse_identifier(id, settings.delimiter))
    return native.call(ns, "get_table_stats", req)
