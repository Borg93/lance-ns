"""lance-ray — the dummy Ray ingest job that is the HEAD of the medallion pipeline (FastAPI entry).

Event-driven head (GOAL 4 B2): ``POST /produce`` (with ``compute_enabled``) seeds a real ``raw_events``
Lance dataset and emits ONE OpenLineage event for it. It does NOT itself publish ``medallion.raw`` — this
app also *subscribes* to the shared lineage topic (``/raw-arrival``), reacts to a raw-dataset write event,
and publishes the trigger the ``raw→bronze`` mover consumes. So the cascade is driven by the raw-data
*arrival event*, not the call: every stage, the head included, reacts to an event on the bus. What drives
it is specifically a COMPLETE write whose output matches ``raw_namespace``/``raw_dataset`` (``raw`` /
``raw_events``) — this dummy today, or a real Ray raw-ingest job that writes that same dataset. (An
ordinary catalog table write does NOT: its output namespace/name won't match the raw filter — the head
reacts to the *raw* dataset, not to any write.) In production the head is a real Ray Data job emitting the
same event; here it is a dummy emitter, which is all the event-driven demo needs.

Run: ``uvicorn medallion.producer:app``. Publishes/subscribes through the local Dapr sidecar (best-effort).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from common.dapr_auth import assert_app_token_configured
from dapr.aio.clients import DaprClient
from fastapi import FastAPI

from medallion.api.health import router as health_router
from medallion.api.produce import router as produce_router
from medallion.api.raw_arrival import register_raw_arrival_route
from medallion.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail closed if behind a Dapr sidecar but the app-token is unset — /raw-arrival would otherwise be an
    # open forged-trigger path (symmetric with the movers + lineage). No-op in dev (dapr_enabled off).
    app.state.startup_complete = False
    app.state.shutting_down = False
    assert_app_token_configured(dapr_enabled=get_settings().dapr_enabled)
    # The Dapr client targets the local sidecar (localhost) — cheap to build, no broker reachability
    # needed at boot. The sidecar persists publishes to NATS JetStream; no DLQ (docs/RESILIENCE.md gap #2).
    app.state.dapr = DaprClient()
    app.state.startup_complete = True
    try:
        yield
    finally:
        app.state.shutting_down = True
        with suppress(Exception):
            await app.state.dapr.close()


_docs = get_settings().docs_enabled  # gate /docs + /openapi.json (off in prod), like the catalog
app = FastAPI(
    title="lance-ray (medallion producer)",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
app.include_router(health_router)
app.include_router(produce_router)
# The event-driven cascade head: subscribe to the lineage topic; a raw-dataset write fires medallion.raw.
register_raw_arrival_route(app)
