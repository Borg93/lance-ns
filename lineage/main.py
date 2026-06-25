"""Lineage service — FastAPI app: ingest OpenLineage events, query the graph.

A sibling microservice to the catalog (it owns the AGE graph; nobody else touches
it). Run: ``uvicorn lineage.main:app``. See ``docs/LINEAGE.md``.
"""

from __future__ import annotations

import logging
from collections import deque
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
    EventRecord,
    Events,
    LineageGraph,
    Neighbors,
    Producers,
    Runs,
    RunStatus,
)

log = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = make_pool(settings.database_url)
    await pool.open()
    app.state.pool = pool
    app.state.repository = LineageRepository(pool, settings.graph)
    # Recent-events ring buffer for the Marquez-style /events feed (in-memory, demo/observability).
    app.state.events = deque(maxlen=500)
    app.state.event_seq = 0
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
async def ingest_event(
    event: RunEvent, repository: RepositoryDep, token: CurrentToken, request: Request
) -> dict[str, str]:
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
    request.app.state.event_seq += 1
    request.app.state.events.append(
        {
            "seq": request.app.state.event_seq,
            "run_id": event.run.run_id,
            "event_type": event.event_type,
            "event_time": event.event_time,
            "job": f"{event.job.namespace}/{event.job.name}",
            "author": event.author,
            "inputs": [d.name for d in event.inputs],
            "outputs": [d.name for d in event.outputs],
            "event": event.model_dump(by_alias=True),
        }
    )
    return {"status": "ingested", "run": event.run.run_id}


@app.get("/runs", tags=["query"])
async def get_runs(request: Request) -> Runs:
    """Live run-status board — current state per run, folded from the lifecycle events (last-wins).

    The provenance graph is terminal-only; this surfaces START/RUNNING/COMPLETE/FAIL so the UI can show
    what's queued / running (with progress) / failed / done *right now*. In-memory (demo/observability).
    """
    folded: dict[str, RunStatus] = {}
    for record in getattr(request.app.state, "events", []):
        run_id = record.get("run_id")
        if not run_id:
            continue
        status = folded.get(run_id)
        if status is None:
            status = RunStatus(run_id=run_id, started_at=record.get("event_time"))
            folded[run_id] = status
        status.events += 1
        status.state = record.get("event_type")  # chronological buffer -> last event wins
        status.updated_at = record.get("event_time")
        status.job = record.get("job") or status.job
        status.author = record.get("author") or status.author
        if record.get("outputs"):
            status.outputs = record["outputs"]
        run_facets = ((record.get("event") or {}).get("run") or {}).get("facets") or {}
        progress = run_facets.get("progress")
        if isinstance(progress, dict):
            status.progress_done = progress.get("done")
            status.progress_total = progress.get("total")
        error = run_facets.get("errorMessage")
        if isinstance(error, dict):
            status.error_message = error.get("message")
    return Runs(runs=sorted(folded.values(), key=lambda r: r.updated_at or "", reverse=True))


@app.get("/events", tags=["query"])
async def get_events(request: Request) -> Events:
    """The most-recent ingested OpenLineage events (newest first) — the Marquez-style event feed.

    In-memory + ungated (demo/observability). In production this would be persisted and gated like
    the per-dataset query endpoints.
    """
    buffer = list(getattr(request.app.state, "events", []))
    return Events(events=[EventRecord(**record) for record in reversed(buffer)])


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
