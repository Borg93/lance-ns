"""Lineage service — FastAPI app: ingest OpenLineage events, query the graph.

A sibling microservice to the catalog (it owns the AGE graph; nobody else touches
it). Run: ``uvicorn lineage.main:app``. See ``docs/LINEAGE.md``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from lance_namespace import LanceNamespaceError

from app.core import fga
from app.core.exceptions import problem_detail
from app.core.oidc import OIDCVerifier
from lineage import demo
from lineage.age import make_pool
from lineage.auth import (
    CurrentToken,
    DatasetFilter,
    FilterDep,
    SettingsDep,
    enforce_author,
    require_metadata_access,
)
from lineage.config import get_settings, storage_options
from lineage.models import RunEvent
from lineage.reconcile import read_storage_version, reconcile
from lineage.repository import LineageRepository
from lineage.schemas import (
    Creator,
    Events,
    LineageGraph,
    Neighbors,
    Producers,
    ReconcileStatus,
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

# /events fetches a wider window than it returns so the visibility filter (which can drop rows) still
# yields up to _RETURN newest *visible* events, not "the visible subset of the newest _RETURN". (#22 audit)
_EVENTS_FETCH = 2000
_EVENTS_RETURN = 500


async def _governed(
    datasets: DatasetFilter,
    fga_enabled: bool,
    items: list[Any],
    refs: Callable[[Any], set[str]],
) -> list[Any]:
    """Drop items the caller may not see: any referencing a non-visible dataset, and — when FGA is on —
    any dataset-less item (it would otherwise pass vacuously, leaking run/author/error to a caller with
    no grants). Auth off → ``visible`` is pass-through, so nothing is dropped. (#22 audit)
    """
    referenced = {name for item in items for name in refs(item)}
    visible = await datasets.visible(list(referenced))
    kept: list[Any] = []
    for item in items:
        names = refs(item)
        if fga_enabled and not names:
            continue
        if names <= visible:
            kept.append(item)
    return kept


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
    # The durable events feed is a *secondary* projection of the authoritative AGE graph (already
    # committed above). Best-effort: a feed-write failure must never 500 an ingest the graph accepted
    # — mirroring the catalog's "lineage must never break a write" stance. (#22 audit)
    try:
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
    except Exception as exc:  # noqa: BLE001 — feed is secondary; the graph write already succeeded
        log.warning("record_event_failed", extra={"run": event.run.run_id, "error": str(exc)})
    return {"status": "ingested", "run": event.run.run_id}


@app.get("/runs", tags=["query"])
async def get_runs(repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep) -> Runs:
    """Live run-status board — each run's current state folded onto its ``(:Run)`` node in Apache AGE.

    **Durable** (survives restart / replica-shared) and **governed** like ``/events`` and the per-dataset
    reads: a run is shown only if the caller ``can_get_metadata`` on every dataset it wrote, so the board
    can't enumerate dataset names / creators / errors outside the caller's reach. Auth off → pass-through.
    """
    result = await repository.list_runs()
    result.runs = await _governed(datasets, settings.fga_enabled, result.runs, lambda r: set(r.outputs))
    return result


@app.get("/events", tags=["query"])
async def get_events(repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep) -> Events:
    """The most-recent ingested OpenLineage events (newest first) — the Marquez-style event feed.

    **Durable** (read from Postgres, survives restart / replica-shared) and **governed**: when auth is
    on the feed is filtered like the per-dataset reads — an event is shown only if the caller
    ``can_get_metadata`` on *every* dataset it references (and a dataset-less event is hidden), so the
    audit feed never discloses a table outside the caller's reach. Auth off → pass-through. (#22)
    """
    records = await repository.list_events(limit=_EVENTS_FETCH)
    visible = await _governed(
        datasets, settings.fga_enabled, records, lambda r: set(r.inputs) | set(r.outputs)
    )
    return Events(events=visible[:_EVENTS_RETURN])


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


@app.get("/datasets/{name}/reconcile", tags=["query"], dependencies=[Depends(require_metadata_access)])
async def get_reconcile(name: str, repository: RepositoryDep, settings: SettingsDep) -> ReconcileStatus:
    """Does the lineage graph agree with the **actual Lance file on storage**? (#23)

    Our moat over format-unaware catalogs (Marquez, Lakekeeper): because we own a Lance lakehouse we
    read the real on-disk version and cross-check it against the version the graph recorded on the
    ``WROTE`` edge — surfacing a write that bypassed lineage (``storage_ahead``) or a lineage claim
    with no data behind it (``missing_on_storage``). Gated on ``can_get_metadata`` for ``name``; the
    Lance read runs in the threadpool so the blocking object-store I/O never stalls the event loop.
    """
    graph_version = await repository.latest_write_version(name)
    uri = await repository.source_uri(name)
    storage_version = (
        await run_in_threadpool(read_storage_version, uri, storage_options(settings))
        if uri is not None
        else None
    )
    return reconcile(dataset=name, graph_version=graph_version, storage_version=storage_version)


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
