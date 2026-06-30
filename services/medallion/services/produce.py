"""The lance-ray producer's ingest business logic — the HEAD of the medallion pipeline.

:func:`produce` is the **first trigger**: it (1) emits an OpenLineage event for the ``raw_events`` dataset
it "ingested" (no inputs — raw is the source) and (2) publishes the first stage trigger to ``medallion.raw``.
The ``raw->bronze`` mover subscribes to that trigger, so lance-ray is one hop upstream of bronze. In
production this is a real Ray Data job writing a Lance table + emitting lineage; here it is a dummy emitter
(no heavy compute), which is all the event-driven demo needs.

Best-effort: a sidecar/broker outage logs + still returns (never 500s the producer) — the catalog contract.
"""

from __future__ import annotations

import json
import logging
import uuid

from dapr.aio.clients import DaprClient

from medallion.core.config import MedallionSettings
from medallion.core.metrics import record_transition
from medallion.schemas.events import build_run_event

log = logging.getLogger(__name__)


async def produce(dapr: DaprClient, settings: MedallionSettings) -> dict[str, str]:
    """Ingest (dummy) the raw dataset and fire the first medallion trigger.

    Emits an OpenLineage event for ``raw_events`` then publishes ``{token, dataset}`` to the raw topic.
    Best-effort: a sidecar/broker outage logs + still returns (the catalog-style contract)."""
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
