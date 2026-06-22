"""Aggregate all v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.security import authenticate
from app.api.v1.endpoints import (
    branches,
    columns,
    data,
    indices,
    namespaces,
    tables,
    tags,
    transactions,
    versions,
    views,
)

# Router-level auth: a no-op when OIDC is disabled, enforced on every route when enabled.
api_router = APIRouter(dependencies=[Depends(authenticate)])
for _module in (namespaces, tables, data, columns, indices, tags, branches, versions, transactions, views):
    api_router.include_router(_module.router)
