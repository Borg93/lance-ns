"""Storage-version reconciliation (#23) — does the lineage graph agree with the actual Lance file?

Marquez and other catalogs are table-format-unaware: they record only what producers *emit*. Because we
own a Lance lakehouse, we can read the **actual on-disk version** and cross-check it against the version
the lineage graph recorded on the ``WROTE`` edge — and flag drift (a write that bypassed lineage, or a
lineage claim with no data behind it). This module is the pure core: a comparator + a thin Lance reader.
The endpoint that exposes it (gated on ``can_get_metadata``) wires these to the graph + storage config.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import lance

from lineage.schemas import DatasetSummary, ReconcileState, ReconcileStatus


def read_storage_version(uri: str, storage_options: dict[str, str]) -> int | None:
    """The current on-disk Lance version at ``uri`` — ``None`` when the dataset isn't there / unreadable.

    A missing dataset is a normal "no storage version" (it may not have been written yet), not an error.
    """
    try:
        return int(lance.dataset(uri, storage_options=storage_options).version)
    except Exception:  # noqa: BLE001 - absent/unreadable dataset → no storage version, not a failure
        return None


def reconcile(*, dataset: str, graph_version: int | None, storage_version: int | None) -> ReconcileStatus:
    """Compare the graph's recorded version against the on-disk version and classify any drift."""
    if graph_version is None and storage_version is None:
        state = ReconcileState.ABSENT
    elif storage_version is None:
        state = ReconcileState.MISSING_ON_STORAGE
    elif graph_version is None:
        state = ReconcileState.UNTRACKED
    elif storage_version == graph_version:
        state = ReconcileState.IN_SYNC
    elif storage_version > graph_version:
        state = ReconcileState.STORAGE_AHEAD
    else:
        state = ReconcileState.GRAPH_AHEAD
    return ReconcileStatus(
        dataset=dataset,
        graph_version=graph_version,
        storage_version=storage_version,
        in_sync=state is ReconcileState.IN_SYNC,
        status=state,
    )


class _ReconcileRepo(Protocol):
    """The repository surface :func:`reconcile_all` needs (kept structural so the core stays testable)."""

    async def list_datasets(
        self, namespace: str | None = ..., tag: str | None = ...
    ) -> list[DatasetSummary]: ...
    async def source_uri(self, name: str) -> str | None: ...
    async def latest_write_version(self, name: str) -> int | None: ...
    async def backfill_write(self, name: str, version: int) -> None: ...


# The drift states that mean a real write's lineage event was LOST — storage has data the graph doesn't fully
# record. Only these are back-filled; GRAPH_AHEAD / MISSING_ON_STORAGE / IN_SYNC are not lost writes.
# Public: the cron route reports the same set, so there is ONE source of truth (no drift-prone duplicate).
BACKFILLABLE_STATES = (ReconcileState.STORAGE_AHEAD, ReconcileState.UNTRACKED)

# The drift states that mean STORAGE lost data the graph still records — the graph claims a version/dataset
# that on-disk Lance no longer has (e.g. an older PVC snapshot restored under the graph, a deleted dataset).
# These are NOT auto-fixable (we can't recreate lost data); the cron surfaces them as a WARNING so a bad
# restore / storage loss is visible instead of silently served as valid provenance.
STORAGE_LOSS_STATES = (ReconcileState.GRAPH_AHEAD, ReconcileState.MISSING_ON_STORAGE)


async def reconcile_all(
    repository: _ReconcileRepo,
    read_version: Callable[[str], Awaitable[int | None]],
    *,
    backfill: bool,
) -> list[ReconcileStatus]:
    """Reconcile every dataset the graph knows against storage; optionally back-fill dropped writes (B4).

    For each dataset carrying a dataSource URI, read the on-disk Lance version (via the injected
    ``read_version``, which the endpoint runs in a threadpool so object-store I/O never stalls the loop) and
    classify drift. When ``backfill`` and storage is AHEAD of — or UNTRACKED by — the graph (the outbox-gap
    signature), stamp the real version onto the graph and re-classify to in-sync. Read-only otherwise.
    """
    results: list[ReconcileStatus] = []
    for summary in await repository.list_datasets():
        uri = await repository.source_uri(summary.name)
        if uri is None:
            continue
        graph_version = await repository.latest_write_version(summary.name)
        storage_version = await read_version(uri)
        status = reconcile(dataset=summary.name, graph_version=graph_version, storage_version=storage_version)
        if backfill and storage_version is not None and status.status in BACKFILLABLE_STATES:
            # Fix the drift as a side effect but keep the found status in the report — a subsequent sweep
            # will show it in_sync, proving the back-fill took.
            await repository.backfill_write(summary.name, storage_version)
        results.append(status)
    return results
