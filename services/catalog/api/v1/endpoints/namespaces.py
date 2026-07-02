"""Namespace metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
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

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, NamespaceDep, SettingsDep
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.services import native

router = APIRouter(prefix="/v1/namespace", tags=["namespace"])


@router.post("/{id}/create", response_model_exclude_none=True)
async def create_namespace(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    body: CreateNamespaceRequest | None = None,
) -> CreateNamespaceResponse:
    """Create a namespace via ``create_namespace``, then seed its FGA owner + parent edge."""
    segments = parse_identifier(id, settings.delimiter)
    req = body or CreateNamespaceRequest()
    req.id = segments
    response: CreateNamespaceResponse = await run_in_threadpool(native.call, ns, "create_namespace", req)
    # Owner + parent edge (parent namespace if nested, else the catalog root) so the
    # concentric cascade reaches the namespace and its tables — stops a nested-namespace
    # lockout and lets a layer-level grant (medallion bronze/silver/gold) reach children.
    await fga_deps.seed_ownership(client, settings, token, resource="namespace", segments=segments)
    return response


@router.get("/{id}/list", response_model_exclude_none=True)
def list_namespaces(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListNamespacesResponse:
    """List the child namespaces under ``id`` via ``list_namespaces`` (page_token/limit paged)."""
    req = ListNamespacesRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_namespaces", req)


@router.post("/{id}/describe", response_model_exclude_none=True)
def describe_namespace(id: str, ns: NamespaceDep, settings: SettingsDep) -> DescribeNamespaceResponse:
    """Return the metadata/properties of namespace ``id`` via ``describe_namespace``."""
    req = DescribeNamespaceRequest(id=parse_identifier(id, settings.delimiter))
    return native.call(ns, "describe_namespace", req)


@router.post("/{id}/drop", response_model_exclude_none=True)
async def drop_namespace(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    client: FgaClientDep,
    body: DropNamespaceRequest | None = None,
) -> DropNamespaceResponse:
    """Drop namespace ``id`` (``drop_namespace``); revoke its FGA tuples so a reused id can't inherit."""
    segments = parse_identifier(id, settings.delimiter)
    req = body or DropNamespaceRequest()
    req.id = segments
    response: DropNamespaceResponse = await run_in_threadpool(native.call, ns, "drop_namespace", req)
    # Revoke the namespace's FGA tuples so a reused id can't inherit stale grants.
    await fga_deps.revoke_ownership(client, settings, resource="namespace", segments=segments)
    return response


@router.post("/{id}/exists", status_code=204)
def namespace_exists(id: str, ns: NamespaceDep, settings: SettingsDep) -> None:
    """Check that namespace ``id`` exists via ``namespace_exists`` — 204 on success, error otherwise."""
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
    """List the tables under namespace ``id`` via ``list_tables`` (page_token/limit paged)."""
    req = ListTablesRequest(id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit)
    return native.call(ns, "list_tables", req)
