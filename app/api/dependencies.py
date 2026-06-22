"""Shared FastAPI dependencies (Annotated type aliases)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from lance_namespace import LanceNamespace

from app.core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_namespace(request: Request) -> LanceNamespace:
    """The backend namespace, built once in the app lifespan."""
    return request.app.state.namespace


NamespaceDep = Annotated[LanceNamespace, Depends(get_namespace)]


def get_storage_options(settings: SettingsDep) -> dict[str, str]:
    """Object-store options (S3/MinIO credentials, region) for direct pylance access."""
    return settings.storage_options()


StorageOptionsDep = Annotated[dict[str, str], Depends(get_storage_options)]
