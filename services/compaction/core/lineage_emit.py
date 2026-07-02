"""Best-effort OpenLineage emission from the compaction service to the lineage graph (#7b).

A maintenance sweep compacts small fragments + GCs old versions of each Lance dataset; when
``lineage_emit_enabled`` is on it records each *materially-compacted* dataset as an OpenLineage
``RunEvent`` (output = the dataset, ``operation=compaction``) published to the **Dapr**
``pubsub.jetstream`` component — the SAME pubsub component + topic the catalog publishes to and the
lineage service subscribes to, so a compaction run shows up in ``producers()`` alongside the writes.
The sidecar owns retry/backoff + trace-propagation (no DLQ — see docs/RESILIENCE.md gap #2) as component
config (no broker client here).

Self-contained: the compaction service never imports the catalog (zero cross-service imports — the
mergeability invariant). The only shared code is ``common.fga`` for the id↔namespace derivation, so the
lineage ``Dataset`` name == the OpenFGA object id == the catalog table id across all three governance axes.

Two deliberate choices:

* **Versionless.** A compaction is *maintenance*, not a data write, so the event asserts no data version —
  the lineage repository records a ``(:Run)-[:WROTE]->(:Dataset)`` with no version and (no inputs →) no
  ``DERIVED_FROM``. This also keeps it out of ``reconcile``'s ``latest_write_version`` (which must track
  real writes), so a compaction never makes the graph look "ahead" of the last data write.
* **Best-effort.** A sidecar/broker outage logs + drops; auditing must never fail a maintenance sweep.

This layer is **pure** (builders + emitter transports only); the per-sweep orchestration that needs the
:class:`~compaction.services.optimize.DatasetResult` type lives in ``compaction.services.sweep`` so ``core``
never imports up into ``services``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from common.openlineage import RUN_EVENT_SCHEMA_URL, custom_facet
from dapr.aio.clients import DaprClient

log = logging.getLogger(__name__)

#: OpenLineage ``lance`` run-facet operation marker for a maintenance pass. Distinct from the catalog's
#: write operations (``create_table`` / ``insert`` / ...); the lineage repository records it as a
#: versionless ``WROTE`` run on the dataset (no ``DERIVED_FROM`` — a compaction has no inputs — and, since
#: it is not ``create_table``, no ``CREATED`` edge).
COMPACTION = "compaction"

#: OpenLineage ``producer`` URI — identifies the software that emitted the event (spec-required).
_PRODUCER = "https://github.com/Borg93/lance-ns/tree/main/services/compaction/core/lineage_emit.py"


def table_id_from_uri(uri: str) -> str | None:
    """Extract the catalog table id from a dataset URI laid out as ``<uuid>_<table_id>``.

    The catalog lays each table out as ``s3://<bucket>/<uuid>_<table_id>/`` (see
    :func:`~compaction.services.optimize.discover_dataset_uris`), and ``table_id`` is the canonical lineage
    ``Dataset`` name == the OpenFGA object id. Splits the last path segment on its **first** ``_`` so a
    table id that itself contains ``_`` survives intact. Returns ``None`` when the segment has no ``_`` (not
    a catalog-laid-out table) so a stray directory never produces a bogus maintenance event.
    """
    name = uri.rstrip("/").split("/")[-1]
    _uuid, sep, table_id = name.partition("_")
    return table_id if sep and table_id else None


def build_maintenance_event(
    *, table_id: str, namespace: str, job_namespace: str, run_id: str, event_time: str
) -> dict[str, Any]:
    """Build the OpenLineage ``RunEvent`` (wire JSON) for one dataset's compaction/GC pass.

    Versionless and input-less: a maintenance pass produces no new logical data and derives from nothing,
    so the lineage repository records a ``(:Run)-[:WROTE]->(:Dataset)`` with no version and no
    ``DERIVED_FROM`` — ``producers()`` then surfaces the compaction run next to the data writes. ``run_id`` /
    ``event_time`` are injected so the builder is pure and deterministically testable.
    """
    return {
        "eventType": "COMPLETE",
        "eventTime": event_time,
        "producer": _PRODUCER,
        "schemaURL": RUN_EVENT_SCHEMA_URL,
        "run": {"runId": run_id, "facets": {"lance": custom_facet(_PRODUCER, operation=COMPACTION)}},
        # Per-table job identity (like the catalog write emitter) — else every dataset's compaction lumps
        # into one ``compaction`` Job node whose output set spans the whole lakehouse.
        "job": {"namespace": job_namespace, "name": f"{COMPACTION}.{table_id}"},
        "inputs": [],
        "outputs": [{"namespace": namespace, "name": table_id}],
    }


@runtime_checkable
class MaintenanceEmitter(Protocol):
    """Emits a compaction maintenance event to the lineage service (best-effort)."""

    async def emit_maintenance(self, *, table_id: str, namespace: str) -> None: ...


class NoopEmitter:
    """The emitter used when lineage emission is disabled (or unwired) — does nothing."""

    async def emit_maintenance(self, *, table_id: str, namespace: str) -> None:  # noqa: ARG002
        return None


class DaprMaintenanceEmitter:
    """Publishes maintenance events to a **Dapr** ``pubsub.jetstream`` component (the production path).

    Publishes to the local Dapr sidecar (``DaprClient.publish_event``); the sidecar persists to NATS
    JetStream and owns retry/backoff (no DLQ — docs/RESILIENCE.md gap #2) + W3C trace-context propagation
    as component config, so the app
    holds no broker client. Best-effort: a sidecar/broker outage logs + drops rather than failing the sweep.
    """

    def __init__(self, client: DaprClient, pubsub: str, topic: str, *, job_namespace: str) -> None:
        self._client = client
        self._pubsub = pubsub
        self._topic = topic
        self._job_namespace = job_namespace

    async def emit_maintenance(self, *, table_id: str, namespace: str) -> None:
        event = build_maintenance_event(
            table_id=table_id,
            namespace=namespace,
            job_namespace=self._job_namespace,
            run_id=str(uuid.uuid4()),
            event_time=datetime.now(UTC).isoformat(),
        )
        try:
            await self._client.publish_event(
                pubsub_name=self._pubsub,
                topic_name=self._topic,
                data=json.dumps(event),
                data_content_type="application/json",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort: lineage must never break a sweep
            log.warning("maintenance_publish_failed", extra={"table": table_id, "error": str(exc)})


def make_emitter(
    *, enabled: bool, dapr: DaprClient | None, pubsub: str, topic: str, job_namespace: str
) -> MaintenanceEmitter:
    """Select the emitter: a Dapr pub/sub publisher when enabled + wired, else a no-op (never silently
    publish nowhere — a half-configured transport stays a no-op rather than pretending to emit)."""
    if enabled and dapr is not None:
        return DaprMaintenanceEmitter(dapr, pubsub, topic, job_namespace=job_namespace)
    return NoopEmitter()
