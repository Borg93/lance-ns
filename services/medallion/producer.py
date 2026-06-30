"""lance-ray — the dummy Ray ingest job that is the HEAD of the medallion pipeline (FastAPI entry).

This is the **first trigger**: on ``POST /produce`` it (1) emits an OpenLineage event for the ``raw_events``
dataset it "ingested" (no inputs — raw is the source), and (2) publishes the first stage trigger to
``medallion.raw``. The ``raw→bronze`` mover subscribes to that trigger and produces bronze — so lance-ray
is one hop upstream of bronze. In production this is a real Ray Data job writing a Lance table + emitting
lineage; here it is a dummy emitter (no heavy compute), which is all the event-driven demo needs.

Run: ``uvicorn medallion.producer:app``. Publishes through the local Dapr sidecar (best-effort).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from dapr.aio.clients import DaprClient
from fastapi import FastAPI

from medallion.api.health import router as health_router
from medallion.api.produce import router as produce_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
