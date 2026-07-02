"""Materialized view endpoints (delegated to the native backend)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    CreateMaterializedViewRequest,
    CreateMaterializedViewResponse,
    RefreshMaterializedViewRequest,
    RefreshMaterializedViewResponse,
)

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, NamespaceDep, SettingsDep
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.services import native

router = APIRouter(prefix="/v1/materialized_view", tags=["materialized_view"])


@router.post("/{id}/create", response_model_exclude_none=True)
async def create_materialized_view(
    id: str,
    body: CreateMaterializedViewRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
) -> CreateMaterializedViewResponse:
    """Create a materialized view via the native backend's ``create_materialized_view``.

    Then seeds FGA ownership on the ``table`` type so the creator keeps refresh/read rights on it.
    """
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: CreateMaterializedViewResponse = await run_in_threadpool(
        native.call, ns, "create_materialized_view", body
    )
    # An MV is scoped to the ``table`` FGA type and create is gated on the parent — without
    # seeding ownership the creator would be locked out of refresh/reads on their own view.
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    return response


@router.post("/{id}/refresh", response_model_exclude_none=True)
def refresh_materialized_view(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: RefreshMaterializedViewRequest | None = None
) -> RefreshMaterializedViewResponse:
    """Rematerialize a materialized view via the native backend's ``refresh_materialized_view``."""
    req = body or RefreshMaterializedViewRequest()
    req.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "refresh_materialized_view", req)
