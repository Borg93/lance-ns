"""Materialized view endpoints (delegated to the native backend)."""

from __future__ import annotations

from fastapi import APIRouter
from lance_namespace import (
    CreateMaterializedViewRequest,
    CreateMaterializedViewResponse,
    RefreshMaterializedViewRequest,
    RefreshMaterializedViewResponse,
)

from app.api.dependencies import NamespaceDep, SettingsDep
from app.core.identifiers import parse_identifier
from app.services import native

router = APIRouter(prefix="/v1/materialized_view", tags=["materialized_view"])


@router.post("/{id}/create", response_model_exclude_none=True)
def create_materialized_view(
    id: str, body: CreateMaterializedViewRequest, ns: NamespaceDep, settings: SettingsDep
) -> CreateMaterializedViewResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "create_materialized_view", body)


@router.post("/{id}/refresh", response_model_exclude_none=True)
def refresh_materialized_view(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: RefreshMaterializedViewRequest | None = None
) -> RefreshMaterializedViewResponse:
    req = body or RefreshMaterializedViewRequest()
    req.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "refresh_materialized_view", req)
