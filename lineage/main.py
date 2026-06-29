"""Lineage service — FastAPI app: ingest OpenLineage events, query the graph.

A sibling microservice to the catalog (it owns the AGE graph; nobody else touches
it). Run: ``uvicorn lineage.main:app``. See ``docs/LINEAGE.md``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from lance_namespace import LanceNamespaceError

from app.core import fga
from app.core.exceptions import problem_detail
from app.core.oidc import OIDCVerifier
from lineage import demo
from lineage.age import make_pool
from lineage.auth import CurrentToken, FilterDep, enforce_author, require_metadata_access
from lineage.config import get_settings
from lineage.models import RunEvent
from lineage.repository import LineageRepository
from lineage.schemas import (
    Creator,
    Events,
    LineageGraph,
    Neighbors,
    Producers,
    Runs,
)

log = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = make_pool(settings.database_url)
    await pool.open()
    app.state.pool = pool
    repository = LineageRepository(pool, settings.graph)
    app.state.repository = repository
    # Durable events feed: a Postgres table created on first boot. /runs folds onto the AGE (:Run)
    # node; both now survive restart + are replica-shared — no in-memory state. (#22)
    await repository.ensure_events_table()
    # Auth is opt-in; when enabled, reuse the catalog's verifier + the shared OpenFGA store.
    if settings.oidc_enabled and settings.oidc_issuer and settings.oidc_audience:
        app.state.oidc = OIDCVerifier(
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_cache_ttl,
            leeway=settings.oidc_leeway,
            allow_insecure=settings.oidc_allow_insecure,
        )
    if settings.fga_enabled and settings.fga_store_id and settings.fga_model_id:
        app.state.fga = fga.make_client(
            settings.fga_api_url,
            settings.fga_store_id,
            settings.fga_model_id,
            timeout_seconds=settings.fga_timeout_seconds,
        )
    try:
        yield
    finally:
        fga_client = getattr(app.state, "fga", None)
        if fga_client is not None:
            await fga_client.close()
        await pool.close()


app = FastAPI(title="Lance Lineage Service", version="0.1.0", lifespan=lifespan)


@app.exception_handler(LanceNamespaceError)
async def handle_domain_error(request: Request, exc: LanceNamespaceError) -> JSONResponse:
    """Render auth/availability failures (401 / 403 / 503) as RFC 9457 problem+json."""
    status, body = problem_detail(exc)
    if status >= 500:
        log.exception(
            "domain_error",
            extra={"method": request.method, "path": request.url.path, "status": status},
        )
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


def get_repository(request: Request) -> LineageRepository:
    """The lineage repository, built once in the lifespan over the AGE pool."""
    return request.app.state.repository


RepositoryDep = Annotated[LineageRepository, Depends(get_repository)]


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/lineage", status_code=201, tags=["ingest"])
async def ingest_event(event: RunEvent, repository: RepositoryDep, token: CurrentToken) -> dict[str, str]:
    """Ingest one OpenLineage ``RunEvent`` into the lineage graph.

    This is the OpenLineage HTTP-transport default path, so any OpenLineage producer
    (our emitter, Airflow, Spark, dbt, …) configured with ``OPENLINEAGE_URL`` pointed
    here ingests with no glue — the lightweight-Marquez contract.

    When OIDC is enabled the ``CurrentToken`` dependency requires a verified bearer token
    (401 otherwise) and :func:`~lineage.auth.enforce_author` binds the run author to that
    token's subject — a producer cannot self-assert someone else's identity.
    """
    enforce_author(event, token)
    await repository.ingest_event(event)
    await repository.record_event(
        run_id=event.run.run_id,
        event_type=event.event_type,
        event_time=event.event_time,
        job=f"{event.job.namespace}/{event.job.name}",
        author=event.author,
        inputs=[d.name for d in event.inputs],
        outputs=[d.name for d in event.outputs],
        event=event.model_dump(by_alias=True),
    )
    return {"status": "ingested", "run": event.run.run_id}


@app.get("/runs", tags=["query"])
async def get_runs(repository: RepositoryDep) -> Runs:
    """Live run-status board — each run's current state folded onto its ``(:Run)`` node in Apache AGE.

    **Durable**: survives a service restart and is shared across replicas (the provenance graph and the
    run lifecycle live in the same AGE store, not an in-memory buffer). Surfaces START/RUNNING/
    COMPLETE/FAIL + progress + error so the UI shows what's queued / running / failed / done right now.
    """
    return await repository.list_runs()


@app.get("/events", tags=["query"])
async def get_events(repository: RepositoryDep, datasets: FilterDep) -> Events:
    """The most-recent ingested OpenLineage events (newest first) — the Marquez-style event feed.

    **Durable** (read from Postgres, survives restart / replica-shared) and **governed**: when auth is
    on the feed is filtered like the per-dataset reads — an event is shown only if the caller
    ``can_get_metadata`` on *every* dataset it references (inputs + outputs), so the audit feed never
    discloses a table outside the caller's reach. Auth off → pass-through (dev/observability). (#22)
    """
    records = await repository.list_events()
    referenced = {name for record in records for name in (*record.inputs, *record.outputs)}
    visible = await datasets.visible(list(referenced))
    events = [r for r in records if set(r.inputs) <= visible and set(r.outputs) <= visible]
    return Events(events=events)


@app.get("/datasets/{name}/upstream", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_upstream(name: str, repository: RepositoryDep, datasets: FilterDep) -> Neighbors:
    """What ``name`` was derived from (provenance).

    Gated on ``can_get_metadata`` for ``name``; related datasets the caller may not see are
    dropped so the graph can't disclose tables outside its reach.
    """
    result = await repository.upstream(name)
    visible = await datasets.visible([ref.name for ref in result.related])
    result.related = [ref for ref in result.related if ref.name in visible]
    return result


@app.get("/datasets/{name}/downstream", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_downstream(name: str, repository: RepositoryDep, datasets: FilterDep) -> Neighbors:
    """What derives from ``name`` (impact). Gated; non-visible related datasets are dropped."""
    result = await repository.downstream(name)
    visible = await datasets.visible([ref.name for ref in result.related])
    result.related = [ref for ref in result.related if ref.name in visible]
    return result


@app.get("/datasets/{name}/producers", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_producers(name: str, repository: RepositoryDep) -> Producers:
    """The runs that wrote ``name`` — who / when / how. Gated on ``can_get_metadata``."""
    return await repository.producers(name)


@app.get("/datasets/{name}/creator", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_creator(name: str, repository: RepositoryDep) -> Creator:
    """Who created ``name`` (the verified catalog principal). Gated on ``can_get_metadata``."""
    return await repository.creator(name)


@app.get("/datasets/{name}/graph", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_graph(name: str, repository: RepositoryDep, datasets: FilterDep) -> LineageGraph:
    """The connected lineage subgraph around ``name`` (nodes + edges) for a DAG view.

    Nodes the caller may not see (and edges touching them) are dropped; the requested ``name``
    is already authorized by the route gate.
    """
    result = await repository.graph(name)
    visible = await datasets.visible([node.id for node in result.nodes if node.id != name])
    visible.add(name)
    result.nodes = [node for node in result.nodes if node.id in visible]
    result.edges = [e for e in result.edges if e.source in visible and e.target in visible]
    return result


# Demo data peek (reads the real Lance datasets on S3) — mounted only when explicitly enabled.
if get_settings().demo_data_enabled:
    app.include_router(demo.router)

# Thin demo UI — a single self-contained page that polls the query endpoints to render the live
# medallion DAG (see scripts/medallion_demo.py). Mounted last so it never shadows an API route.
_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_STATIC), html=True), name="ui")
