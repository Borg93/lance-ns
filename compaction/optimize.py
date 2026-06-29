"""The compaction + GC core — infra-light so the discovery + aggregation logic is unit-testable.

``discover_dataset_uris`` is pure list-logic over a pyarrow filesystem; ``compact_one`` wraps the two
blocking Lance maintenance calls. Both keep IO at the edges so the orchestration can be tested with fakes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import lance
import pyarrow.fs as pafs
from pydantic import BaseModel


class DatasetResult(BaseModel):
    """What one dataset's maintenance pass did (or why it was skipped)."""

    uri: str
    fragments_removed: int = 0
    fragments_added: int = 0
    old_versions_removed: int = 0
    bytes_removed: int = 0
    error: str | None = None


def discover_dataset_uris(fs: pafs.FileSystem, bucket: str) -> list[str]:
    """Top-level directories under ``bucket`` that are datasets — skipping the catalog's ``__manifest``
    (and any other ``__`` bookkeeping dir). The catalog lays each table out as ``<uuid>_<table_id>/``."""
    uris: list[str] = []
    for info in fs.get_file_info(pafs.FileSelector(bucket, recursive=False)):
        if info.type != pafs.FileType.Directory:
            continue
        name = info.path.rstrip("/").split("/")[-1]
        if name.startswith("__"):
            continue
        uris.append(f"s3://{info.path}")
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
        stats: Any = ds.cleanup_old_versions(older_than=older_than)
        result.old_versions_removed = int(getattr(stats, "old_versions", 0))
        result.bytes_removed = int(getattr(stats, "bytes_removed", 0))
    except Exception as exc:  # noqa: BLE001 — maintenance is best-effort per dataset
        result.error = f"maintain: {exc}"
    return result
