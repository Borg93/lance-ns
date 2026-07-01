"""The event-driven cascade head — react to a 'raw batch written' lineage event by firing the pipeline.

lance-ray subscribes to the shared lineage topic (the same events the catalog + producer already emit on a
write) and, **only** for a write to the raw namespace/dataset, publishes the raw stage trigger
(``medallion.raw``) that the raw->bronze mover consumes. So the cascade HEAD is driven by the raw-data
*arrival event*, not a manual call or a timer — every stage, the head included, reacts to an event on the
bus we already run.

**Loop-guarded**: the lineage topic also carries the movers' own bronze/silver/gold writes; those are acked
and ignored (their output namespace isn't raw), so publishing the trigger can never re-fire the head.
Best-effort with ``RETRY`` so a sidecar/broker outage is redelivered rather than dropped.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from dapr.aio.clients import DaprClient

from medallion.core.config import MedallionSettings
from medallion.core.metrics import record_transition

log = logging.getLogger(__name__)

_SUCCESS = {"status": "SUCCESS"}
_RETRY = {"status": "RETRY"}


def _writes_raw(event: dict[str, Any], settings: MedallionSettings) -> bool:
    """True iff this OpenLineage event records a write to the raw dataset (the cascade's entry point)."""
    outputs = event.get("outputs") or []
    return any(
        isinstance(o, dict)
        and o.get("namespace") == settings.raw_namespace
        and o.get("name") == settings.raw_dataset
        for o in outputs
    )


async def handle_raw_arrival(dapr: DaprClient, settings: MedallionSettings, event: Any) -> dict[str, str]:
    """Fire the cascade head when a raw-dataset write arrives; ack-and-ignore everything else.

    ``event`` is the untrusted Dapr CloudEvent envelope (hence ``Any`` + the ``isinstance`` guards); its
    ``data`` is the OpenLineage run event. Only a write to ``raw_namespace``/``raw_dataset`` publishes the
    ``medallion.raw`` trigger — a downstream mover's event (bronze/silver/gold) is acked and skipped, so the
    head never self-triggers (loop guard). A publish outage returns ``RETRY`` for redelivery.
    """
    data = event.get("data") if isinstance(event, dict) else None
    if not isinstance(data, dict) or not _writes_raw(data, settings):
        return _SUCCESS  # not a raw write — ack so Dapr doesn't redeliver, but drive nothing
    run = data.get("run")
    token = str(run.get("runId")) if isinstance(run, dict) and run.get("runId") else uuid.uuid4().hex[:12]
    trigger = {"token": token, "dataset": settings.raw_dataset, "namespace": settings.raw_namespace}
    try:
        await dapr.publish_event(
            pubsub_name=settings.pubsub,
            topic_name=settings.raw_topic,
            data=json.dumps(trigger),
            data_content_type="application/json",
        )
        record_transition(f"source->{settings.raw_namespace}")
    except Exception as exc:  # noqa: BLE001 — RETRY so the sidecar redelivers the raw-arrival event
        log.warning("medallion_raw_arrival_publish_failed", extra={"token": token, "error": str(exc)})
        return _RETRY
    log.info("medallion_cascade_triggered", extra={"token": token, "dataset": settings.raw_dataset})
    return _SUCCESS
