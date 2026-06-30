"""The maintenance sweep: discover every dataset in the bucket, compact + GC each, aggregate the result.

Keeps the blocking S3/Lance orchestration out of the route so the cron handler stays a thin shell and the
aggregation (:func:`summarize`) stays unit-testable without S3.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pyarrow.fs as pafs
from common import fga

from compaction.core.config import CompactionSettings
from compaction.core.lineage_emit import MaintenanceEmitter, table_id_from_uri
from compaction.core.metrics import record_reclaimed, record_run
from compaction.services.optimize import DatasetResult, compact_one, discover_dataset_uris


def _s3fs(settings: CompactionSettings) -> pafs.S3FileSystem:
    """A pyarrow S3 filesystem over the (dev, HTTP) RustFS endpoint — used only to LIST the bucket."""
    endpoint = settings.s3_endpoint.removeprefix("http://").removeprefix("https://")
    return pafs.S3FileSystem(
        endpoint_override=endpoint,
        access_key=settings.s3_access_key_id,
        secret_key=settings.s3_secret_access_key,
        scheme="http",
        region=settings.s3_region,
    )


def run_sweep(settings: CompactionSettings) -> list[DatasetResult]:
    """Discover every dataset in the bucket and compact + GC each; record what the sweep reclaimed."""
    older_than = timedelta(days=settings.older_than_days)
    options = settings.storage_options()
    uris = discover_dataset_uris(_s3fs(settings), settings.s3_bucket)
    results = [compact_one(uri, options, older_than) for uri in uris]
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
    """Emit a best-effort maintenance event per dataset the sweep MATERIALLY compacted/GC'd (#7b).

    Skips datasets that errored (the pass didn't complete), that reclaimed nothing (a no-op tick), or whose
    URI isn't the catalog's ``<uuid>_<table_id>`` layout (no id to key on). The parent namespace is derived
    from the id via :func:`common.fga.parent_namespace_id` so the event lands on the SAME ``(:Dataset)`` the
    catalog created and never clobbers its namespace. Awaited inline so each publish reaches the durable
    Dapr/JetStream transport before the cron handler returns; ``emit_maintenance`` is itself best-effort, so
    this loop never raises into the sweep.
    """
    for result in results:
        if result.error is not None or not _did_material_work(result):
            continue
        table_id = table_id_from_uri(result.uri)
        if table_id is None:
            continue
        namespace = fga.parent_namespace_id(table_id, delimiter=delimiter) or ""
        await emitter.emit_maintenance(table_id=table_id, namespace=namespace)


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
