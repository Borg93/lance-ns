"""Table branch endpoints (delegated to the native backend).

Branch models exist in lance-namespace 0.8.x; the native ``DirectoryNamespace``
does not yet implement branch ops, so these return a spec-correct 501 until a
managed/REST backend provides them.
"""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    CreateTableBranchRequest,
    CreateTableBranchResponse,
    DeleteTableBranchRequest,
    DeleteTableBranchResponse,
    ListTableBranchesRequest,
    ListTableBranchesResponse,
)

from app.api.dependencies import NamespaceDep, SettingsDep
from app.core.identifiers import parse_identifier
from app.services import native

router = APIRouter(prefix="/v1/table", tags=["branch"])


@router.post("/{id}/branches/list", response_model_exclude_none=True)
def list_table_branches(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    page_token: str | None = None,
    limit: int | None = None,
) -> ListTableBranchesResponse:
    req = ListTableBranchesRequest(
        id=parse_identifier(id, settings.delimiter), page_token=page_token, limit=limit
    )
    return native.call(ns, "list_table_branches", req)


@router.post("/{id}/branches/create", response_model_exclude_none=True)
def create_table_branch(
    id: str, body: CreateTableBranchRequest, ns: NamespaceDep, settings: SettingsDep
) -> CreateTableBranchResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_table_branch", body)


@router.post("/{id}/branches/delete", response_model_exclude_none=True)
def delete_table_branch(
    id: str, body: DeleteTableBranchRequest, ns: NamespaceDep, settings: SettingsDep
) -> DeleteTableBranchResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "delete_table_branch", body)
