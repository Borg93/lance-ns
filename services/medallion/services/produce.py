"""The lance-ray producer's ingest business logic — the dummy raw writer at the head of the pipeline.

:func:`produce` (with ``compute_enabled``) seeds a real ``raw_events`` Lance dataset, then emits ONE
OpenLineage event announcing that write. It does NOT itself trigger the cascade — lance-ray's own
``/raw-arrival`` subscription (:mod:`medallion.services.ingest_trigger`) reacts to that raw-write event and
publishes the ``medallion.raw`` trigger, so the pipeline is driven by the raw-data-arrival EVENT, not this
call (GOAL 4 B2). In production this is a real Ray Data job; here it is a dummy emitter, which is all the
event-driven demo needs.

Best-effort: a sidecar/broker outage logs + still returns (never 500s the producer) — the catalog contract.
"""

from __future__ import annotations

import json
import logging
import uuid

from common import dapr_publish
from dapr.aio.clients import DaprClient
from fastapi.concurrency import run_in_threadpool
from opentelemetry import trace

from medallion.core.config import MedallionSettings
from medallion.schemas.events import build_run_event
from medallion.services.compute import seed_raw

log = logging.getLogger(__name__)
# Manual INTERNAL span over the threadpool Lance seed — auto-instrumentation can't see the compute step.
tracer = trace.get_tracer(__name__)


async def produce(dapr: DaprClient, settings: MedallionSettings) -> dict[str, str]:
    """Ingest the raw dataset and emit its write event (the event-driven cascade head).

    With ``compute_enabled`` it FIRST seeds a real ``raw_events`` Lance dataset (the fake lance-ray ingest)
    so the emitted lineage carries the real version; off → a dummy emit (version 1). It then emits ONE
    OpenLineage event for ``raw_events``. It does NOT publish ``medallion.raw`` — lance-ray's ``/raw-arrival``
    subscription reacts to this raw-write event and fires the trigger, so the cascade is event-driven.
    Best-effort: a sidecar/broker outage logs + still returns (the catalog-style contract)."""
    token = uuid.uuid4().hex[:12]
    result = None
    if settings.compute_enabled and settings.raw_uri:
        # Fake-Ray ingest: a REAL Lance write of raw_events (blocking IO → threadpool) → the real version
        # + the measured output statistics (rows + on-disk bytes) the emit records as outputStatistics.
        with tracer.start_as_current_span("medallion.produce") as span:
            result = await run_in_threadpool(seed_raw, settings.raw_uri, settings.storage_options())
            span.set_attribute("lance.version", result.version)
            span.set_attribute("lance.row_count", result.row_count)
            span.set_attribute("lance.size_bytes", result.size_bytes)
    raw_event = build_run_event(
        operation=settings.producer_operation,
        author=settings.producer_author,
        job_namespace=settings.job_namespace,
        inputs=[],
        output_namespace=settings.raw_namespace,
        output_name=settings.raw_dataset,
        version=result.version if result else 1,
        row_count=result.row_count if result else None,
        size_bytes=result.size_bytes if result else None,
        source_uri=settings.raw_uri if result else None,
        token=token,
    )
    try:
        # The cascade HEAD is this raw-write lineage event: lance-ray's own /raw-arrival subscription reacts
        # to it and publishes the medallion.raw trigger, so the pipeline is driven by the arrival EVENT, not
        # by this call directly (event-driven head — the trigger publish moved to ingest_trigger.py).
        await dapr_publish.publish_event(
            dapr,
            timeout_seconds=settings.publish_timeout_seconds,
            pubsub_name=settings.pubsub,
            topic_name=settings.lineage_topic,
            data=json.dumps(raw_event),
            data_content_type="application/json",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort: a publish outage must not 500 the producer
        log.warning("medallion_produce_failed", extra={"token": token, "error": str(exc)})
        return {"status": "publish_failed", "token": token}
    log.info("medallion_produced", extra={"token": token, "dataset": settings.raw_dataset})
    return {"status": "produced", "token": token, "dataset": settings.raw_dataset}
