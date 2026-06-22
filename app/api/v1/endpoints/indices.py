"""Index endpoints (delegated to the native backend)."""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    CreateTableIndexRequest,
    CreateTableIndexResponse,
    DescribeTableIndexStatsRequest,
    DescribeTableIndexStatsResponse,
    DropTableIndexRequest,
    DropTableIndexResponse,
    ListTableIndicesRequest,
    ListTableIndicesResponse,
)

from app.api.dependencies import NamespaceDep, SettingsDep
from app.core.identifiers import parse_identifier
from app.services import native

router = APIRouter(prefix="/v1/table", tags=["index"])


@router.post("/{id}/create_index", response_model_exclude_none=True)
def create_index(
    id: str, body: CreateTableIndexRequest, ns: NamespaceDep, settings: SettingsDep
) -> CreateTableIndexResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_table_index", body)


@router.post("/{id}/create_scalar_index", response_model_exclude_none=True)
def create_scalar_index(
    id: str, body: CreateTableIndexRequest, ns: NamespaceDep, settings: SettingsDep
) -> CreateTableIndexResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_table_scalar_index", body)


@router.post("/{id}/index/list", response_model_exclude_none=True)
def list_table_indices(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTableIndicesResponse:
    req = ListTableIndicesRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_table_indices", req)


@router.post("/{id}/index/{index_name}/stats", response_model_exclude_none=True)
def describe_table_index_stats(
    id: str, index_name: str, ns: NamespaceDep, settings: SettingsDep
) -> DescribeTableIndexStatsResponse:
    req = DescribeTableIndexStatsRequest(id=parse_identifier(id, settings.delimiter), index_name=index_name)
    return native.call(ns, "describe_table_index_stats", req)


@router.post("/{id}/index/{index_name}/drop", response_model_exclude_none=True)
def drop_table_index(
    id: str, index_name: str, ns: NamespaceDep, settings: SettingsDep
) -> DropTableIndexResponse:
    req = DropTableIndexRequest(id=parse_identifier(id, settings.delimiter), index_name=index_name)
    return native.call(ns, "drop_table_index", req)
