"""Aggregate all v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from catalog.api.fga_deps import authorize
from catalog.api.v1.endpoints import (
    branches,
    columns,
    credentials,
    data,
    indices,
    namespaces,
    tables,
    tags,
    transactions,
    versions,
    views,
)

# Router-level authn + authz (via authorize, which composes the OIDC token):
# a no-op when both are disabled, enforced per route when enabled.
api_router = APIRouter(dependencies=[Depends(authorize)])
for _module in (
    namespaces,
    tables,
    data,
    columns,
    indices,
    tags,
    branches,
    versions,
    transactions,
    views,
    credentials,
):
    api_router.include_router(_module.router)
