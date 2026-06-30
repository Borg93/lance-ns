"""Unit tests for the compaction service core — infra-free (no S3, no Lance).

Pins the two pieces of logic that aren't just Lance calls: dataset discovery (skip the catalog's
``__manifest`` + non-directories) and the sweep summary aggregation.
"""

from __future__ import annotations

from typing import Any, cast

import pyarrow.fs as pafs
from compaction.services.optimize import DatasetResult, discover_dataset_uris
from compaction.services.sweep import summarize


class _FakeFS:
    """Returns a fixed FileInfo list from get_file_info (the only method discover_dataset_uris calls)."""

    def __init__(self, infos: list[pafs.FileInfo]) -> None:
        self._infos = infos

    def get_file_info(self, _selector: Any) -> list[pafs.FileInfo]:
        return self._infos


def test_discover_skips_manifest_and_non_dirs() -> None:
    fs = _FakeFS(
        [
            pafs.FileInfo("lance-catalog/abcd_ns$table", pafs.FileType.Directory),
            pafs.FileInfo("lance-catalog/__manifest", pafs.FileType.Directory),  # bookkeeping → skip
            pafs.FileInfo("lance-catalog/loose.txt", pafs.FileType.File),  # not a dataset → skip
            pafs.FileInfo("lance-catalog/efgh_gold$catalog", pafs.FileType.Directory),
        ]
    )
    uris = discover_dataset_uris(cast(Any, fs), "lance-catalog")
    assert uris == ["s3://lance-catalog/abcd_ns$table", "s3://lance-catalog/efgh_gold$catalog"]


def test_summarize_aggregates_reclaimed_and_errors() -> None:
    results = [
        DatasetResult(uri="s3://b/a", fragments_removed=3, old_versions_removed=2),
        DatasetResult(uri="s3://b/b", fragments_removed=1, old_versions_removed=0),
        DatasetResult(uri="s3://b/c", error="open: not a dataset"),
    ]
    summary = summarize(results)
    assert summary["datasets"] == 3
    assert summary["fragments_removed"] == 4
    assert summary["versions_removed"] == 2
    # failures keep their message (the why), not just the URI
    assert summary["errors"] == {"s3://b/c": "open: not a dataset"}
