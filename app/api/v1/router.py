"""Aggregate all v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter

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

api_router = APIRouter()
for _module in (namespaces, tables, data, columns, indices, tags, branches, versions, transactions, views):
    api_router.include_router(_module.router)
