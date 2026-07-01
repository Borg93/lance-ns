"""Unit tests for storage-version reconciliation (#23) + the outbox back-fill (GOAL 4 B4)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import lance
import pyarrow as pa
import pytest
from lineage.core.reconcile import read_storage_version, reconcile, reconcile_all
from lineage.schemas import DatasetSummary, ReconcileState


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


# --- B4: reconcile_all + the outbox back-fill ------------------------------------------------ #


class _FakeRepo:
    """Records back-fills; returns canned graph versions + dataSource URIs (no DB)."""

    def __init__(
        self, datasets: list[str], graph_versions: dict[str, int], uris: dict[str, str | None]
    ) -> None:
        self._datasets = [DatasetSummary(name=n) for n in datasets]
        self._graph = graph_versions
        self._uris = uris
        self.backfilled: list[tuple[str, int]] = []

    async def list_datasets(
        self, namespace: str | None = None, tag: str | None = None
    ) -> list[DatasetSummary]:  # noqa: ARG002
        return list(self._datasets)

    async def source_uri(self, name: str) -> str | None:
        return self._uris.get(name)

    async def latest_write_version(self, name: str) -> int | None:
        return self._graph.get(name)

    async def backfill_write(self, name: str, version: int) -> None:
        self.backfilled.append((name, version))


def _reader(storage: dict[str, int]) -> Callable[[str], Awaitable[int | None]]:
    async def read(uri: str) -> int | None:
        return storage.get(uri.rsplit("/", 1)[-1])  # uri = s3://b/<name>

    return read


def test_reconcile_all_backfills_only_lost_write_states() -> None:
    repo = _FakeRepo(
        datasets=["ahead", "untracked", "insync", "graph_ahead", "no_uri"],
        graph_versions={"ahead": 1, "insync": 2, "graph_ahead": 3},  # untracked / no_uri not in graph
        uris={
            "ahead": "s3://b/ahead",
            "untracked": "s3://b/untracked",
            "insync": "s3://b/insync",
            "graph_ahead": "s3://b/graph_ahead",
            "no_uri": None,  # no dataSource facet → skipped, never read
        },
    )
    read = _reader({"ahead": 3, "untracked": 2, "insync": 2, "graph_ahead": 1})

    statuses = asyncio.run(reconcile_all(cast(Any, repo), read, backfill=True))

    # Only storage-ahead + untracked (a real write the graph missed) back-fill, at the storage version.
    assert sorted(repo.backfilled) == [("ahead", 3), ("untracked", 2)]
    by_status = {s.dataset: s.status for s in statuses}
    assert by_status["ahead"] == ReconcileState.STORAGE_AHEAD
    assert by_status["untracked"] == ReconcileState.UNTRACKED
    assert by_status["insync"] == ReconcileState.IN_SYNC
    assert by_status["graph_ahead"] == ReconcileState.GRAPH_AHEAD  # graph newer than disk — not a lost write
    assert "no_uri" not in by_status  # skipped: no dataSource URI to read


def test_reconcile_all_read_only_reports_but_writes_nothing() -> None:
    repo = _FakeRepo(datasets=["ahead"], graph_versions={"ahead": 1}, uris={"ahead": "s3://b/ahead"})

    statuses = asyncio.run(reconcile_all(cast(Any, repo), _reader({"ahead": 5}), backfill=False))

    assert repo.backfilled == []  # read-only mode never writes
    assert statuses[0].status == ReconcileState.STORAGE_AHEAD
