"""Tag endpoints (implemented via the pylance data plane)."""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    CreateTableTagRequest,
    CreateTableTagResponse,
    DeleteTableTagRequest,
    DeleteTableTagResponse,
    GetTableTagVersionRequest,
    GetTableTagVersionResponse,
    ListTableTagsRequest,
    ListTableTagsResponse,
    UpdateTableTagRequest,
    UpdateTableTagResponse,
)

from app.api.dependencies import NamespaceDep, SettingsDep, StorageOptionsDep
from app.core.identifiers import parse_identifier
from app.services import dataplane

router = APIRouter(prefix="/v1/table", tags=["tag"])


@router.post("/{id}/tags/list", response_model_exclude_none=True)
def list_table_tags(
    id: str, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> ListTableTagsResponse:
    req = ListTableTagsRequest(id=parse_identifier(id, settings.delimiter))
    return dataplane.list_tags(ns, so, req)


@router.post("/{id}/tags/create", response_model_exclude_none=True)
def create_table_tag(
    id: str, body: CreateTableTagRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> CreateTableTagResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.create_tag(ns, so, body)


@router.post("/{id}/tags/version", response_model_exclude_none=True)
def get_table_tag_version(
    id: str, body: GetTableTagVersionRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> GetTableTagVersionResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.get_tag_version(ns, so, body)


@router.post("/{id}/tags/update", response_model_exclude_none=True)
def update_table_tag(
    id: str, body: UpdateTableTagRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> UpdateTableTagResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.update_tag(ns, so, body)


@router.post("/{id}/tags/delete", response_model_exclude_none=True)
def delete_table_tag(
    id: str, body: DeleteTableTagRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> DeleteTableTagResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.delete_tag(ns, so, body)
