"""Table metadata + lifecycle endpoints (no data plane)."""

from __future__ import annotations

from fastapi import APIRouter
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

from app.api.dependencies import NamespaceDep, SettingsDep
from app.core.identifiers import parse_identifier
from app.services import native

router = APIRouter(prefix="/v1/table", tags=["table"])


@router.get("/", response_model_exclude_none=True)
def list_all_tables(
    ns: NamespaceDep, page_token: str | None = None, limit: int | None = None
) -> ListTablesResponse:
    req = ListTablesRequest(id=[], page_token=page_token, limit=limit)
    return native.call(ns, "list_all_tables", req)


@router.post("/{id}/declare", response_model_exclude_none=True)
def declare_table(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: DeclareTableRequest | None = None
) -> DeclareTableResponse:
    req = body or DeclareTableRequest()
    req.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "declare_table", req)


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
def drop_table(id: str, ns: NamespaceDep, settings: SettingsDep) -> DropTableResponse:
    return native.call(ns, "drop_table", DropTableRequest(id=parse_identifier(id, settings.delimiter)))


@router.post("/{id}/deregister", response_model_exclude_none=True)
def deregister_table(id: str, ns: NamespaceDep, settings: SettingsDep) -> DeregisterTableResponse:
    req = DeregisterTableRequest(id=parse_identifier(id, settings.delimiter))
    return native.call(ns, "deregister_table", req)


@router.post("/{id}/register", response_model_exclude_none=True)
def register_table(
    id: str, body: RegisterTableRequest, ns: NamespaceDep, settings: SettingsDep
) -> RegisterTableResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "register_table", body)


@router.post("/{id}/rename", response_model_exclude_none=True)
def rename_table(
    id: str, body: RenameTableRequest, ns: NamespaceDep, settings: SettingsDep
) -> RenameTableResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "rename_table", body)


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
