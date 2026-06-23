"""Lineage service — FastAPI app: ingest OpenLineage events, query the graph.

A sibling microservice to the catalog (it owns the AGE graph; nobody else touches
it). Run: ``uvicorn lineage.main:app``. See ``docs/LINEAGE.md``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request

from lineage.age import make_pool
from lineage.config import get_settings
from lineage.models import RunEvent
from lineage.repository import LineageRepository
from lineage.schemas import LineageGraph, Neighbors, Producers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = make_pool(settings.database_url)
    await pool.open()
    app.state.pool = pool
    app.state.repository = LineageRepository(pool, settings.graph)
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Lance Lineage Service", version="0.1.0", lifespan=lifespan)


def get_repository(request: Request) -> LineageRepository:
    """The lineage repository, built once in the lifespan over the AGE pool."""
    return request.app.state.repository


RepositoryDep = Annotated[LineageRepository, Depends(get_repository)]


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/lineage", status_code=201, tags=["ingest"])
async def ingest_event(event: RunEvent, repository: RepositoryDep) -> dict[str, str]:
    """Ingest one OpenLineage ``RunEvent`` into the lineage graph.

    This is the OpenLineage HTTP-transport default path, so any OpenLineage producer
    (our emitter, Airflow, Spark, dbt, …) configured with ``OPENLINEAGE_URL`` pointed
    here ingests with no glue — the lightweight-Marquez contract.
    """
    await repository.ingest_event(event)
    return {"status": "ingested", "run": event.run.run_id}


@app.get("/datasets/{name}/upstream", tags=["query"])
async def get_upstream(name: str, repository: RepositoryDep) -> Neighbors:
    """What ``name`` was derived from (provenance)."""
    return await repository.upstream(name)


@app.get("/datasets/{name}/downstream", tags=["query"])
async def get_downstream(name: str, repository: RepositoryDep) -> Neighbors:
    """What derives from ``name`` (impact)."""
    return await repository.downstream(name)


@app.get("/datasets/{name}/producers", tags=["query"])
async def get_producers(name: str, repository: RepositoryDep) -> Producers:
    """The runs that wrote ``name`` — who / when / how."""
    return await repository.producers(name)


@app.get("/datasets/{name}/graph", tags=["query"])
async def get_graph(name: str, repository: RepositoryDep) -> LineageGraph:
    """The connected lineage subgraph around ``name`` (nodes + edges) for a DAG view."""
    return await repository.graph(name)
