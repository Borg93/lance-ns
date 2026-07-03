"""The compaction + GC core — infra-light so the discovery + aggregation logic is unit-testable.

``discover_dataset_uris`` is pure list-logic over a pyarrow filesystem; ``compact_one`` wraps the two
blocking Lance maintenance calls. Both keep IO at the edges so the orchestration can be tested with fakes.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import lance
import pyarrow.fs as pafs
from pydantic import BaseModel

log = logging.getLogger(__name__)


class DatasetResult(BaseModel):
    """What one dataset's maintenance pass did (or why it was skipped)."""

    uri: str
    fragments_removed: int = 0
    fragments_added: int = 0
    indices_optimized: int = 0
    old_versions_removed: int = 0
    bytes_removed: int = 0
    error: str | None = None


def discover_dataset_uris(fs: pafs.FileSystem, bucket: str, *, max_depth: int = 3) -> list[str]:
    """Lance datasets under ``bucket`` — a directory IS a dataset iff it has a ``_versions/`` child
    (the Lance table-layout marker); any other directory is a namespace prefix and is recursed into
    (bounded by ``max_depth``). Skips ``__`` bookkeeping dirs (the catalog's ``__manifest``).

    The catalog lays top-level tables out as ``<uuid>_<table_id>/``, but the medallion cascade nests
    its datasets one level down (``medallion/raw`` …) — without the marker probe the sweep both
    reported the ``medallion/`` prefix as a failed dataset AND never maintained the real ones under it.
    """
    uris: list[str] = []

    def _walk(prefix: str, depth: int) -> None:
        for info in fs.get_file_info(pafs.FileSelector(prefix, recursive=False)):
            if info.type != pafs.FileType.Directory:
                continue
            name = info.path.rstrip("/").split("/")[-1]
            if name.startswith("__"):
                continue
            marker = fs.get_file_info(f"{info.path}/_versions")
            if marker.type == pafs.FileType.Directory:
                uris.append(f"s3://{info.path}")
            elif depth < max_depth:
                _walk(info.path, depth + 1)

    _walk(bucket, 1)
    return uris


def compact_one(uri: str, storage_options: dict[str, str], older_than: timedelta) -> DatasetResult:
    """Compact small fragments + GC old versions for one dataset. Never raises — a per-dataset failure is
    captured in ``error`` so one bad dataset can't abort the whole maintenance pass."""
    try:
        ds = lance.dataset(uri, storage_options=storage_options)
    except Exception as exc:  # noqa: BLE001 — not a Lance dataset / unreadable → skip, don't abort
        return DatasetResult(uri=uri, error=f"open: {exc}")
    result = DatasetResult(uri=uri)
    try:
        metrics: Any = ds.optimize.compact_files()
        result.fragments_removed = int(getattr(metrics, "fragments_removed", 0))
        result.fragments_added = int(getattr(metrics, "fragments_added", 0))
        # Keep secondary indices (vector ANN / scalar / FTS) covering the new fragments. WITHOUT this a
        # freshly-written row isn't in the index → vector/filter queries either miss it or fall back to a
        # flat scan. Index optimize is a maintenance op exactly like compaction (Lance does it distributed
        # via lance-ray; here single-process). Idempotent. Own guard so a no-index dataset can't fail it.
        try:
            ds.optimize.optimize_indices()
            result.indices_optimized = len(ds.list_indices())
        except Exception as exc:  # noqa: BLE001 — no indices / transient → don't fail the whole sweep
            log.warning("optimize_indices_skipped", extra={"uri": uri, "error": str(exc)})
        # error_if_tagged_old_versions=False: tagged versions are EXEMPT from GC (they survive until the tag
        # is deleted). The default (True) RAISES once any tag ages past older_than — which, since the catalog
        # creates long-lived promotion tags, would permanently stall GC for that dataset (the raise is caught
        # and recorded as error, reclaiming nothing). We want GC to skip tagged versions and reclaim the rest.
        stats: Any = ds.cleanup_old_versions(older_than=older_than, error_if_tagged_old_versions=False)
        result.old_versions_removed = int(getattr(stats, "old_versions", 0))
        result.bytes_removed = int(getattr(stats, "bytes_removed", 0))
    except Exception as exc:  # noqa: BLE001 — maintenance is best-effort per dataset
        result.error = f"maintain: {exc}"
    return result
