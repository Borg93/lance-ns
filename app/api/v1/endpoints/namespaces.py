"""Namespace metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    CreateNamespaceRequest,
    CreateNamespaceResponse,
    DescribeNamespaceRequest,
    DescribeNamespaceResponse,
    DropNamespaceRequest,
    DropNamespaceResponse,
    ListNamespacesRequest,
    ListNamespacesResponse,
    ListTablesRequest,
    ListTablesResponse,
    NamespaceExistsRequest,
)

from app.api.dependencies import NamespaceDep, SettingsDep
from app.core.identifiers import parse_identifier
from app.services import native

router = APIRouter(prefix="/v1/namespace", tags=["namespace"])


@router.post("/{id}/create", response_model_exclude_none=True)
def create_namespace(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: CreateNamespaceRequest | None = None
) -> CreateNamespaceResponse:
    req = body or CreateNamespaceRequest()
    req.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_namespace", req)


@router.get("/{id}/list", response_model_exclude_none=True)
def list_namespaces(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListNamespacesResponse:
    req = ListNamespacesRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_namespaces", req)


@router.post("/{id}/describe", response_model_exclude_none=True)
def describe_namespace(id: str, ns: NamespaceDep, settings: SettingsDep) -> DescribeNamespaceResponse:
    req = DescribeNamespaceRequest(id=parse_identifier(id, settings.delimiter))
    return native.call(ns, "describe_namespace", req)


@router.post("/{id}/drop", response_model_exclude_none=True)
def drop_namespace(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: DropNamespaceRequest | None = None
) -> DropNamespaceResponse:
    req = body or DropNamespaceRequest()
    req.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "drop_namespace", req)


@router.post("/{id}/exists", status_code=204)
def namespace_exists(id: str, ns: NamespaceDep, settings: SettingsDep) -> None:
    req = NamespaceExistsRequest(id=parse_identifier(id, settings.delimiter))
    native.call(ns, "namespace_exists", req)


@router.get("/{id}/table/list", response_model_exclude_none=True)
def list_tables(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTablesResponse:
    req = ListTablesRequest(id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit)
    return native.call(ns, "list_tables", req)
