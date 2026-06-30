"""The maintenance sweep: discover every dataset in the bucket, compact + GC each, aggregate the result.

Keeps the blocking S3/Lance orchestration out of the route so the cron handler stays a thin shell and the
aggregation (:func:`summarize`) stays unit-testable without S3.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pyarrow.fs as pafs

from compaction.core.config import CompactionSettings
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
