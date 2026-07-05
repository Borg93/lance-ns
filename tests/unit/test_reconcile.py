"""Unit tests for storage-version reconciliation (#23) + the outbox back-fill (GOAL 4 B4)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import lance
import pyarrow as pa
import pytest
from lineage.api.reconcile_cron import _on_cron
from lineage.core.config import LineageSettings
from lineage.core.reconcile import read_storage_version, reconcile, reconcile_all
from lineage.schemas import DatasetSummary, ReconcileState


def _settings(**values: Any) -> LineageSettings:
    return LineageSettings.model_validate(values)


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


# --- item 6: the cron route's single-flight guard ------------------------------------------- #


class _LockRepo(_FakeRepo):
    """A ``_FakeRepo`` plus a ``reconcile_lock`` that yields a canned acquired flag, and records whether the
    sweep body actually ran (``list_datasets`` is the first thing ``reconcile_all`` touches)."""

    def __init__(self, *, acquired: bool) -> None:
        # uri None → reconcile_all skips the storage read (no real S3), but list_datasets still runs, which
        # is all we assert: that the sweep BODY executed (vs the skip path returning before it).
        super().__init__(datasets=["d"], graph_versions={"d": 1}, uris={"d": None})
        self._acquired = acquired
        self.swept = False

    @asynccontextmanager
    async def reconcile_lock(self) -> AsyncIterator[bool]:
        yield self._acquired

    async def list_datasets(
        self, namespace: str | None = None, tag: str | None = None
    ) -> list[DatasetSummary]:
        self.swept = True
        return await super().list_datasets(namespace, tag)


def test_cron_skips_when_another_sweep_holds_the_lock() -> None:
    repo = _LockRepo(acquired=False)

    result = asyncio.run(_on_cron(cast(Any, repo), _settings(), None))

    assert result["skipped"] is True  # single-flight: a busy tick returns skipped
    assert repo.swept is False  # and never touches the graph (no double-driven back-fill)


def test_cron_runs_the_sweep_when_it_acquires_the_lock() -> None:
    repo = _LockRepo(acquired=True)

    result = asyncio.run(_on_cron(cast(Any, repo), _settings(), None))

    assert repo.swept is True  # acquired → the sweep ran
    assert "checked" in result and "skipped" not in result
    assert "storage_loss" in result  # the sweep always reports the (possibly empty) storage-loss set


def test_storage_loss_states_flag_graph_ahead_and_missing_not_insync() -> None:
    # The states that mean STORAGE lost data the graph still records (surfaced as WARN, not auto-fixed) —
    # distinct from the back-fillable "graph lost the event" set. Guards the classification the cron reports.
    from lineage.core.reconcile import BACKFILLABLE_STATES, STORAGE_LOSS_STATES

    assert ReconcileState.GRAPH_AHEAD in STORAGE_LOSS_STATES
    assert ReconcileState.MISSING_ON_STORAGE in STORAGE_LOSS_STATES
    assert ReconcileState.IN_SYNC not in STORAGE_LOSS_STATES
    assert not set(STORAGE_LOSS_STATES) & set(BACKFILLABLE_STATES)  # loss ≠ back-fillable (disjoint)
