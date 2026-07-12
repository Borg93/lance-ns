"""Table version endpoints (delegated to the native backend / external manifest store)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
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

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, NamespaceDep, SettingsDep
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.services import native

# The native dir backend implements create / describe / batch-delete versions, but its bindings are typed
# ``request: dict`` (not the pydantic model) — ``native.call`` marshals the request to a dict for those, so
# these delegate directly and return real results instead of the marshalling-bug 501 they surfaced before.
router = APIRouter(prefix="/v1/table", tags=["version"])


@router.post("/version/batch-create", response_model_exclude_none=True)
def batch_create_table_versions(
    body: BatchCreateTableVersionsRequest, ns: NamespaceDep
) -> BatchCreateTableVersionsResponse:
    """Atomically create version entries for multiple tables — delegates to the native
    ``batch_create_table_versions`` (implemented by the 0.9 dir backend)."""
    return native.call(ns, "batch_create_table_versions", body)


@router.post("/batch-commit", response_model_exclude_none=True)
async def batch_commit_tables(
    body: BatchCommitTablesRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
) -> BatchCommitTablesResponse:
    """Atomic multi-table commit — delegates to the native ``batch_commit_tables``.

    OWNERSHIP PARITY with ``/declare`` (audit 2026-07-12): a ``declare_table`` sub-op CREATES a table
    (``_authorize_batch`` gated it as create-on-parent), so the creator must be seeded owner + parent
    edge exactly like the dedicated route — without this, a batch-declared table had NO owner tuple
    (fail-closed asymmetry: the creator couldn't manage their own table at owner tier, and the
    reused-id revoke assumptions didn't hold). ``seed_ownership`` is a no-op with FGA off.
    """
    response: BatchCommitTablesResponse = await run_in_threadpool(
        native.call, ns, "batch_commit_tables", body
    )
    for operation in body.operations or []:
        declare = getattr(operation, "declare_table", None)
        segments = getattr(declare, "id", None) if declare is not None else None
        if segments:
            await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    return response


@router.post("/{id}/version/list", response_model_exclude_none=True)
def list_table_versions(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
    descending: bool | None = None,
    branch: str | None = None,
) -> ListTableVersionsResponse:
    """List the versions of table ``id`` via ``list_table_versions``; ``descending=true`` guarantees
    latest-to-oldest ordering, ``branch`` targets a non-main branch (spec 0.9 query params)."""
    req = ListTableVersionsRequest(
        id=parse_identifier(id, settings.delimiter),
        page_token=page_token,
        limit=limit,
        descending=descending,
        branch=branch,
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
    """Describe one table version (the latest when ``version`` is omitted).

    Backed by the native dir backend, which returns a spec-correct ``TableVersion`` (with ``manifest_path``
    / ``manifest_size`` / ``e_tag`` / ``timestamp``); ``native.call`` marshals the request to the dict the
    binding expects. A missing version raises the backend's ``TableVersionNotFoundError`` → 404.
    """
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
