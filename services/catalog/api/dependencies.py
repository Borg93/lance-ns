"""Shared FastAPI dependencies (Annotated type aliases)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from lance_namespace import LanceNamespace
from openfga_sdk import OpenFgaClient

from catalog.core.config import Settings, get_settings
from catalog.core.lineage_emit import LineageEmitter, NoopEmitter

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_namespace(request: Request) -> LanceNamespace:
    """The backend namespace, built once in the app lifespan."""
    return request.app.state.namespace


NamespaceDep = Annotated[LanceNamespace, Depends(get_namespace)]


def get_fga_client(request: Request) -> OpenFgaClient | None:
    """The wired OpenFGA client from catalog.state, or ``None`` when FGA isn't provisioned.

    One place that knows where the client lives (``app.state.fga``), injected like
    ``NamespaceDep`` instead of re-spelled as ``getattr(request.app.state, "fga", None)``
    in every create/seed/list handler.
    """
    return getattr(request.app.state, "fga", None)


FgaClientDep = Annotated[OpenFgaClient | None, Depends(get_fga_client)]


def get_storage_options(settings: SettingsDep) -> dict[str, str]:
    """Object-store options (S3/MinIO credentials, region) for direct pylance access."""
    return settings.storage_options()


StorageOptionsDep = Annotated[dict[str, str], Depends(get_storage_options)]


def get_lineage_emitter(request: Request) -> LineageEmitter:
    """The lineage emitter built in the app lifespan — a no-op when emission is disabled."""
    emitter = getattr(request.app.state, "lineage_emitter", None)
    return emitter if emitter is not None else NoopEmitter()


LineageEmitterDep = Annotated[LineageEmitter, Depends(get_lineage_emitter)]
