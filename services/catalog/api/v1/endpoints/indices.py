"""Index endpoints (delegated to the native backend).

A build/drop bumps the Lance version (new manifest) without changing data or columns, so each emits a
best-effort versioned lineage ``WROTE`` event (operation ``create_index`` / ``drop_index``) — provenance of
when a scalar/vector index was (re)built or removed. The native responses carry only a ``transaction_id``, so
the produced version is read back off the dataset (like insert/restore).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    CreateTableIndexRequest,
    CreateTableIndexResponse,
    CreateTableScalarIndexResponse,
    DescribeTableIndexStatsRequest,
    DescribeTableIndexStatsResponse,
    DropTableIndexRequest,
    DropTableIndexResponse,
    ListTableIndicesRequest,
    ListTableIndicesResponse,
)

from catalog.api.dependencies import LineageEmitterDep, NamespaceDep, SettingsDep, StorageOptionsDep
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.core.lineage_emit import CREATE_INDEX, DROP_INDEX, emit_write_event
from catalog.services import dataplane, native

router = APIRouter(prefix="/v1/table", tags=["index"])


async def _emit_index_write(
    *,
    emitter: LineageEmitterDep,
    ns: NamespaceDep,
    so: StorageOptionsDep,
    settings: SettingsDep,
    token: CurrentToken,
    segments: list[str],
    operation: str,
    authorization: str | None,
) -> None:
    """Emit a best-effort versioned WROTE for an index build/drop (the new manifest version + current
    schema, which the index op leaves unchanged), reading both back off the dataset."""
    version = await run_in_threadpool(dataplane.current_version, ns, so, segments)
    schema_fields = await run_in_threadpool(dataplane.read_schema_fields, ns, so, segments)
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=version,
        operation=operation,
        authorization=authorization,
        schema_fields=schema_fields,
    )


@router.post("/{id}/create_index", response_model_exclude_none=True)
async def create_index(
    id: str,
    body: CreateTableIndexRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CreateTableIndexResponse:
    """Build a vector index on a table's column — wraps the native ``create_table_index`` op; emits a
    CREATE_INDEX lineage event at the new version."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: CreateTableIndexResponse = await run_in_threadpool(native.call, ns, "create_table_index", body)
    await _emit_index_write(
        emitter=emitter,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        segments=segments,
        operation=CREATE_INDEX,
        authorization=authorization,
    )
    return response


@router.post("/{id}/create_scalar_index", response_model_exclude_none=True)
async def create_scalar_index(
    id: str,
    body: CreateTableIndexRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CreateTableScalarIndexResponse:
    """Build a scalar index on a table's column — wraps the native ``create_table_scalar_index`` op; emits a
    CREATE_INDEX lineage event at the new version."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: CreateTableScalarIndexResponse = await run_in_threadpool(
        native.call, ns, "create_table_scalar_index", body
    )
    await _emit_index_write(
        emitter=emitter,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        segments=segments,
        operation=CREATE_INDEX,
        authorization=authorization,
    )
    return response


@router.post("/{id}/index/list", response_model_exclude_none=True)
def list_table_indices(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTableIndicesResponse:
    """List the indices defined on a table (paged) — wraps the native ``list_table_indices`` op."""
    req = ListTableIndicesRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_table_indices", req)


@router.post("/{id}/index/{index_name}/stats", response_model_exclude_none=True)
def describe_table_index_stats(
    id: str, index_name: str, ns: NamespaceDep, settings: SettingsDep
) -> DescribeTableIndexStatsResponse:
    """Report stats for a named index on a table — wraps the native ``describe_table_index_stats`` op."""
    req = DescribeTableIndexStatsRequest(id=parse_identifier(id, settings.delimiter), index_name=index_name)
    return native.call(ns, "describe_table_index_stats", req)


@router.post("/{id}/index/{index_name}/drop", response_model_exclude_none=True)
async def drop_table_index(
    id: str,
    index_name: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> DropTableIndexResponse:
    """Drop a named index from a table — wraps the native ``drop_table_index`` op; emits a DROP_INDEX
    lineage event at the new version."""
    segments = parse_identifier(id, settings.delimiter)
    req = DropTableIndexRequest(id=segments, index_name=index_name)
    response: DropTableIndexResponse = await run_in_threadpool(native.call, ns, "drop_table_index", req)
    await _emit_index_write(
        emitter=emitter,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        segments=segments,
        operation=DROP_INDEX,
        authorization=authorization,
    )
    return response
