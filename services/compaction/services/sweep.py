"""The maintenance sweep: discover every dataset in the bucket, compact + GC each, aggregate the result.

Keeps the blocking S3/Lance orchestration out of the route so the cron handler stays a thin shell and the
aggregation (:func:`summarize`) stays unit-testable without S3.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta
from typing import Any

import pyarrow.fs as pafs
from common import fga
from common.objectfs import s3_filesystem
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from compaction.core.config import CompactionSettings
from compaction.core.lineage_emit import MaintenanceEmitter, table_id_from_uri
from compaction.core.metrics import record_reclaimed, record_run
from compaction.services.optimize import DatasetResult, compact_one, discover_dataset_uris

log = logging.getLogger(__name__)

#: Per-tick cap on FAIL-event publishes. Each publish is already bounded by the emitter's 5s timeout and
#: the batch is gathered concurrently, but an unbounded fan-out over a bucket where EVERYTHING is failing
#: could still push the cron handler past the 30s Dapr ack window — cap it, and LOG what was dropped
#: (a silent cap would read as "covered everything"). The over-cap set is SHUFFLED before the cut: the
#: discovery listing order is deterministic, so a fixed head-slice would re-drop the SAME datasets every
#: tick and their FAIL would never emit — shuffling gets every failing dataset through within a few ticks,
#: converging on its deterministic run id (review 2026-07-10).
_MAX_FAIL_EMITS_PER_TICK = 25

# Each compact+GC is blocking Lance/S3 work invisible to auto-instrumentation — a per-dataset INTERNAL
# span lets a slow or failing compaction be localized in the trace instead of hiding in the cron handler.
tracer = trace.get_tracer(__name__)


def _s3fs(settings: CompactionSettings) -> pafs.S3FileSystem:
    """A pyarrow S3 filesystem over the RustFS endpoint — used only to LIST the bucket."""
    return s3_filesystem(settings.storage_options())


def run_sweep(settings: CompactionSettings) -> list[DatasetResult]:
    """Discover every dataset in EVERY swept bucket and compact + GC each; record what was reclaimed.

    MULTI-BUCKET (audit 2026-07-14). This used to sweep exactly ONE bucket, so every #3-A per-warehouse
    bucket and #3-B multi-base data bucket was invisible to GC — their tables accumulated superseded
    manifest versions and small fragments FOREVER. A storage leak created by the very features that
    introduce new buckets. A bucket that does not exist (or is unreadable) is skipped, not fatal: one
    missing tenant bucket must not stop the sweep for everyone else.
    """
    older_than = timedelta(days=settings.older_than_days)
    options = settings.storage_options()
    fs = _s3fs(settings)
    uris: list[str] = []
    for bucket in settings.sweep_buckets:
        try:
            found = discover_dataset_uris(fs, bucket)
        except Exception as exc:  # noqa: BLE001 — one bad bucket must not blind the sweep to the others
            log.warning("compaction_bucket_skipped", extra={"bucket": bucket, "error": str(exc)})
            continue
        log.info("compaction_bucket_discovered", extra={"bucket": bucket, "datasets": len(found)})
        uris.extend(found)
    results: list[DatasetResult] = []
    for uri in uris:
        with tracer.start_as_current_span("compaction.compact") as span:
            span.set_attribute("lance.dataset_uri", uri)
            result = compact_one(uri, options, older_than)
            results.append(result)
            # compact_one never raises (it captures the per-dataset error), so reflect a failure on the
            # span explicitly — else a failed dataset looks identical to a clean one in the trace.
            if result.error is not None:
                span.set_status(StatusCode.ERROR, result.error)
                if result.error_type:  # error.type: stable class name so error spans aggregate
                    span.set_attribute("error.type", result.error_type)
    record_run()
    record_reclaimed(
        fragments_removed=sum(r.fragments_removed for r in results),
        versions_removed=sum(r.old_versions_removed for r in results),
        indices_optimized=sum(r.indices_optimized for r in results),
    )
    return results


def _did_material_work(result: DatasetResult) -> bool:
    """Did the pass actually reclaim anything (fragments merged or old versions GC'd)?

    We record a maintenance event only when something material happened — a cron that re-sweeps every
    dataset on each tick would otherwise flood the lineage graph with no-op compaction runs.
    """
    return bool(result.fragments_removed or result.old_versions_removed)


async def emit_sweep_lineage(
    emitter: MaintenanceEmitter, results: list[DatasetResult], *, delimiter: str
) -> None:
    """Emit a best-effort maintenance event per swept dataset: COMPLETE for material work, FAIL for a
    terminal per-dataset failure (#7b + the §4 failure-visibility item).

    Selection:

    * ``maintain:``-errored → a **FAIL** event (compact/GC escaped Lance's own auto-retry — terminal for
      this tick; before this, a persistently failing dataset surfaced only in OTel spans + a cron response
      body nobody reads).
    * ``open:``-errored → **no event** (unreadable / declared-only dir — transient non-dataset noise).
    * no error + material work → the **COMPLETE** event (unchanged); no-op ticks skipped.
    * URI not the catalog's ``<uuid>_<table_id>`` layout → skipped either way (no id to key on). This is
      the DOCUMENTED blind spot for the medallion-nested datasets (``s3://<bucket>/medallion/<ns>`` has no
      catalog id to reconstruct — a URI→id map is out of proportion here).

    The parent namespace is derived via :func:`common.fga.parent_namespace_id` so events land on the SAME
    ``(:Dataset)`` the catalog created. COMPLETE emits stay awaited inline (unchanged semantics); the FAIL
    batch is gathered CONCURRENTLY (each publish already bounded by the emitter's 5s timeout) and capped
    at ``_MAX_FAIL_EMITS_PER_TICK`` so a bucket of failing datasets can't push the cron handler past the
    30s Dapr ack window. Every emit is best-effort internally, so nothing here raises into the sweep.
    """
    # One pass derives (table_id, namespace) for BOTH branches — the cap below then counts actual emits
    # (an unparseable maintain:-errored URI must not consume a cap slot while emitting nothing).
    failed: list[tuple[str, str, str]] = []  # (table_id, namespace, error)
    for result in results:
        table_id = table_id_from_uri(result.uri)
        if table_id is None:
            continue
        namespace = fga.parent_namespace_id(table_id, delimiter=delimiter) or ""
        if result.error is not None:
            if result.error.startswith("maintain:"):
                failed.append((table_id, namespace, result.error))
            continue
        if not _did_material_work(result):
            continue
        await emitter.emit_maintenance(table_id=table_id, namespace=namespace)

    if len(failed) > _MAX_FAIL_EMITS_PER_TICK:
        log.warning(
            "maintenance_fail_emits_capped",
            extra={"failing": len(failed), "emitted": _MAX_FAIL_EMITS_PER_TICK},
        )
        random.shuffle(failed)  # fairness under a mass incident — see the cap constant's comment
        failed = failed[:_MAX_FAIL_EMITS_PER_TICK]
    # Raise-proof by construction, not by convention: the emitters swallow internally, but the guardrail
    # ("a publish failure must never fail the sweep") must hold even for a mis-wired emitter — an
    # AttributeError building a coro or a raise inside one is logged per dataset and never reaches the
    # cron handler.
    try:
        outcomes = await asyncio.gather(
            *(emitter.emit_maintenance_failed(table_id=t, namespace=ns, error=err) for t, ns, err in failed),
            return_exceptions=True,
        )
        for (table_id, _ns, _err), outcome in zip(failed, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                log.warning("maintenance_fail_emit_error", extra={"table": table_id, "error": str(outcome)})
    except Exception as exc:  # noqa: BLE001 — best-effort: lineage must never break a sweep
        log.warning("maintenance_fail_emit_error", extra={"error": str(exc)})


def summarize(results: list[DatasetResult]) -> dict[str, Any]:
    """Aggregate one sweep's per-dataset results into the cron response. Failures keep their MESSAGE
    (not just the URI) — a cron sweep has no human watching, so the *why* is the only debugging signal."""
    return {
        "datasets": len(results),
        "fragments_removed": sum(r.fragments_removed for r in results),
        "indices_optimized": sum(r.indices_optimized for r in results),
        "versions_removed": sum(r.old_versions_removed for r in results),
        "errors": {r.uri: r.error for r in results if r.error},
    }
