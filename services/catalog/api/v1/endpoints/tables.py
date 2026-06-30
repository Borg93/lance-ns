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

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, LineageEmitterDep, NamespaceDep, SettingsDep
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.core.lineage_emit import DROP_TABLE, emit_write_event
from catalog.services import native

router = APIRouter(prefix="/v1/table", tags=["table"])


@router.get("", response_model_exclude_none=True)
async def list_all_tables(
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTablesResponse:
    req = ListTablesRequest(id=[], page_token=page_token, limit=limit)
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
    body: DeclareTableRequest | None = None,
) -> DeclareTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    req = body or DeclareTableRequest()
    req.id = segments
    response: DeclareTableResponse = await run_in_threadpool(native.call, ns, "declare_table", req)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    return response


@router.post("/{id}/describe", response_model_exclude_none=True)
def describe_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    with_table_uri: bool | None = None,
    load_detailed_metadata: bool | None = None,
    check_declared: bool | None = None,
    version: int | None = None,
) -> DescribeTableResponse:
    req = DescribeTableRequest(
        id=parse_identifier(id, settings.delimiter),
        with_table_uri=with_table_uri,
        load_detailed_metadata=load_detailed_metadata,
        check_declared=check_declared,
        version=version,
    )
    return native.call(ns, "describe_table", req)


@router.post("/{id}/exists", status_code=204)
def table_exists(id: str, ns: NamespaceDep, settings: SettingsDep) -> None:
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
    segments = parse_identifier(id, settings.delimiter)
    response: DropTableResponse = await run_in_threadpool(
        native.call, ns, "drop_table", DropTableRequest(id=segments)
    )
    # Revoke the table's FGA tuples so a later table reusing this id can't inherit stale grants.
    await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
    # Record the drop as best-effort lineage — provenance of the deletion (the dataset node persists in the
    # graph, named a `drop_table` run). Inline-awaited (NOT BackgroundTasks) → reaches the durable
    # Dapr/JetStream transport before the response; best-effort, so it never fails the drop.
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=None,
        operation=DROP_TABLE,
        authorization=authorization,
    )
    return response


@router.post("/{id}/deregister", response_model_exclude_none=True)
async def deregister_table(
    id: str, ns: NamespaceDep, settings: SettingsDep, client: FgaClientDep
) -> DeregisterTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    response: DeregisterTableResponse = await run_in_threadpool(
        native.call, ns, "deregister_table", DeregisterTableRequest(id=segments)
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
) -> RegisterTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: RegisterTableResponse = await run_in_threadpool(native.call, ns, "register_table", body)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
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
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: RenameTableResponse = await run_in_threadpool(native.call, ns, "rename_table", body)
    # Rename mints a new table identifier under ``new_namespace_id`` (defaulting to the
    # source's parent namespace, i.e. all source segments but the last) + ``new_table_name``;
    # grant ownership on the destination so the caller retains access under the new id.
    dest_parent = list(body.new_namespace_id) if body.new_namespace_id else segments[:-1]
    new_segments = [*dest_parent, body.new_table_name]
    # Revoke the SOURCE id's tuples (it no longer names a table) then seed the destination — so no
    # stale grant survives under the old id and the caller keeps ownership under the new one.
    await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=new_segments)
    return response


@router.post("/{id}/restore", response_model_exclude_none=True)
def restore_table(
    id: str, body: RestoreTableRequest, ns: NamespaceDep, settings: SettingsDep
) -> RestoreTableResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "restore_table", body)


@router.post("/{id}/stats", response_model_exclude_none=True)
def get_table_stats(id: str, ns: NamespaceDep, settings: SettingsDep) -> GetTableStatsResponse:
    req = GetTableStatsRequest(id=parse_identifier(id, settings.delimiter))
    return native.call(ns, "get_table_stats", req)
