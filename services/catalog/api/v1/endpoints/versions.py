"""Table version endpoints (delegated to the native backend / external manifest store)."""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    BatchCommitTablesRequest,
    BatchCommitTablesResponse,
    BatchCreateTableVersionsRequest,
    BatchCreateTableVersionsResponse,
    BatchDeleteTableVersionsRequest,
    BatchDeleteTableVersionsResponse,
    CreateTableVersionRequest,
    CreateTableVersionResponse,
    DescribeTableVersionRequest,
    DescribeTableVersionResponse,
    ListTableVersionsRequest,
    ListTableVersionsResponse,
)

from catalog.api.dependencies import NamespaceDep, SettingsDep
from catalog.core.identifiers import parse_identifier
from catalog.services import native

router = APIRouter(prefix="/v1/table", tags=["version"])


@router.post("/version/batch-create", response_model_exclude_none=True)
def batch_create_table_versions(
    body: BatchCreateTableVersionsRequest, ns: NamespaceDep
) -> BatchCreateTableVersionsResponse:
    return native.call(ns, "batch_create_table_versions", body)


@router.post("/batch-commit", response_model_exclude_none=True)
def batch_commit_tables(body: BatchCommitTablesRequest, ns: NamespaceDep) -> BatchCommitTablesResponse:
    return native.call(ns, "batch_commit_tables", body)


@router.post("/{id}/version/list", response_model_exclude_none=True)
def list_table_versions(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTableVersionsResponse:
    req = ListTableVersionsRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_table_versions", req)


@router.post("/{id}/version/create", response_model_exclude_none=True)
def create_table_version(
    id: str, body: CreateTableVersionRequest, ns: NamespaceDep, settings: SettingsDep
) -> CreateTableVersionResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_table_version", body)


@router.post("/{id}/version/describe", response_model_exclude_none=True)
def describe_table_version(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    version: int | None = None,
    body: DescribeTableVersionRequest | None = None,
) -> DescribeTableVersionResponse:
    req = body or DescribeTableVersionRequest()
    req.id = parse_identifier(id, settings.delimiter)
    if version is not None:
        req.version = version
    return native.call(ns, "describe_table_version", req)


@router.post("/{id}/version/delete", response_model_exclude_none=True)
def batch_delete_table_versions(
    id: str, body: BatchDeleteTableVersionsRequest, ns: NamespaceDep, settings: SettingsDep
) -> BatchDeleteTableVersionsResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "batch_delete_table_versions", body)
