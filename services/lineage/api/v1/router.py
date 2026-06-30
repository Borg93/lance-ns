"""Aggregate the always-on lineage v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter

from lineage.api.v1.endpoints import columns, datasets, ingest, reconcile, runs

api_router = APIRouter()
for _module in (datasets, columns, reconcile, runs, ingest):
    api_router.include_router(_module.router)
