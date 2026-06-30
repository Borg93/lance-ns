"""lance-ray — the dummy Ray ingest job that is the HEAD of the medallion pipeline.

This is the **first trigger**: on ``POST /produce`` it (1) emits an OpenLineage event for the ``raw_events``
dataset it "ingested" (no inputs — raw is the source), and (2) publishes the first stage trigger to
``medallion.raw``. The ``raw→bronze`` mover subscribes to that trigger and produces bronze — so lance-ray
is one hop upstream of bronze. In production this is a real Ray Data job writing a Lance table + emitting
lineage; here it is a dummy emitter (no heavy compute), which is all the event-driven demo needs.

Run: ``uvicorn medallion.producer:app``. Publishes through the local Dapr sidecar (best-effort).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from dapr.aio.clients import DaprClient
from fastapi import FastAPI

from medallion.config import get_settings
from medallion.events import build_run_event
from medallion.metrics import record_transition

log = logging.getLogger(__name__)


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


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/produce", status_code=202, tags=["produce"])
async def produce() -> dict[str, str]:
    """Ingest (dummy) the raw dataset and fire the first medallion trigger.

    Emits an OpenLineage event for ``raw_events`` then publishes ``{token, dataset}`` to the raw topic.
    Best-effort: a sidecar/broker outage logs + still returns (the catalog-style contract)."""
    settings = get_settings()
    token = uuid.uuid4().hex[:12]
    raw_event = build_run_event(
        operation=settings.producer_operation,
        author=settings.producer_author,
        job_namespace=settings.job_namespace,
        inputs=[],
        output_namespace=settings.raw_namespace,
        output_name=settings.raw_dataset,
        run_id=f"{settings.producer_operation}-{token}",
    )
    trigger = {"token": token, "dataset": settings.raw_dataset, "namespace": settings.raw_namespace}
    dapr: DaprClient = app.state.dapr
    try:
        await dapr.publish_event(
            pubsub_name=settings.pubsub,
            topic_name=settings.lineage_topic,
            data=json.dumps(raw_event),
            data_content_type="application/json",
        )
        await dapr.publish_event(
            pubsub_name=settings.pubsub,
            topic_name=settings.raw_topic,
            data=json.dumps(trigger),
            data_content_type="application/json",
        )
        record_transition(f"source->{settings.raw_namespace}")
    except Exception as exc:  # noqa: BLE001 — best-effort: a publish outage must not 500 the producer
        log.warning("medallion_produce_failed", extra={"token": token, "error": str(exc)})
        return {"status": "publish_failed", "token": token}
    log.info("medallion_produced", extra={"token": token, "dataset": settings.raw_dataset})
    return {"status": "produced", "token": token, "dataset": settings.raw_dataset}
