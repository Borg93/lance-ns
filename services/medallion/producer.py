"""lance-ray — the dummy Ray ingest job that is the HEAD of the medallion pipeline (FastAPI entry).

Event-driven head (GOAL 4 B2): ``POST /produce`` (with ``compute_enabled``) seeds a real ``raw_events``
Lance dataset and emits ONE OpenLineage event for it. It does NOT itself publish ``medallion.raw`` — this
app also *subscribes* to the shared lineage topic (``/raw-arrival``), reacts to a raw-dataset write event,
and publishes the trigger the ``raw→bronze`` mover consumes. So the cascade is driven by the raw-data
*arrival event*, not the call: every stage, the head included, reacts to an event on the bus. Any raw writer
(this dummy, or the catalog) that emits a raw-write event drives it. In production the head is a real Ray
Data job emitting the same event; here it is a dummy emitter, which is all the event-driven demo needs.

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
    assert_app_token_configured(dapr_enabled=get_settings().dapr_enabled)
    # The Dapr client targets the local sidecar (localhost) — cheap to build, no broker reachability
    # needed at boot. The sidecar persists publishes to NATS JetStream and owns retry/DLQ.
    app.state.dapr = DaprClient()
    try:
        yield
    finally:
        with suppress(Exception):
            await app.state.dapr.close()


app = FastAPI(title="lance-ray (medallion producer)", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(produce_router)
# The event-driven cascade head: subscribe to the lineage topic; a raw-dataset write fires medallion.raw.
register_raw_arrival_route(app)
