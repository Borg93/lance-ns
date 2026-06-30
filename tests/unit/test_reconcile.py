"""Unit tests for storage-version reconciliation (#23, ``lineage.core.reconcile``)."""

from __future__ import annotations

from pathlib import Path

import lance
import pyarrow as pa
import pytest
from lineage.core.reconcile import read_storage_version, reconcile
from lineage.schemas import ReconcileState


@pytest.mark.parametrize(
    ("graph_version", "storage_version", "expected", "in_sync"),
    [
        (1, 1, ReconcileState.IN_SYNC, True),
        (2, 2, ReconcileState.IN_SYNC, True),
        (1, 2, ReconcileState.STORAGE_AHEAD, False),  # data changed without lineage
        (3, 2, ReconcileState.GRAPH_AHEAD, False),  # lineage claims newer than disk
        (None, 1, ReconcileState.UNTRACKED, False),  # data exists, no lineage write
        (1, None, ReconcileState.MISSING_ON_STORAGE, False),  # graph has it, disk doesn't
        (None, None, ReconcileState.ABSENT, False),
    ],
)
def test_reconcile_classifies_drift(
    graph_version: int | None, storage_version: int | None, expected: ReconcileState, in_sync: bool
) -> None:
    result = reconcile(dataset="a$b", graph_version=graph_version, storage_version=storage_version)
    assert result.status is expected
    assert result.in_sync is in_sync
    assert result.dataset == "a$b"
    assert result.graph_version == graph_version
    assert result.storage_version == storage_version


def test_read_storage_version_returns_on_disk_version(tmp_path: Path) -> None:
    uri = str(tmp_path / "t.lance")
    lance.write_dataset(pa.table({"id": [1, 2]}), uri)
    assert read_storage_version(uri, {}) == 1
    lance.write_dataset(pa.table({"id": [3]}), uri, mode="append")  # a second version
    assert read_storage_version(uri, {}) == 2


def test_read_storage_version_none_when_absent(tmp_path: Path) -> None:
    assert read_storage_version(str(tmp_path / "missing.lance"), {}) is None
