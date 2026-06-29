"""Storage-version reconciliation (#23) — does the lineage graph agree with the actual Lance file?

Marquez and other catalogs are table-format-unaware: they record only what producers *emit*. Because we
own a Lance lakehouse, we can read the **actual on-disk version** and cross-check it against the version
the lineage graph recorded on the ``WROTE`` edge — and flag drift (a write that bypassed lineage, or a
lineage claim with no data behind it). This module is the pure core: a comparator + a thin Lance reader.
The endpoint that exposes it (gated on ``can_get_metadata``) wires these to the graph + storage config.
"""

from __future__ import annotations

import lance

from lineage.schemas import ReconcileState, ReconcileStatus


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
