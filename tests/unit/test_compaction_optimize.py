"""Real-Lance regression tests for the compaction core (`compact_one`) — local filesystem, no S3.

Pins the §4 change: ``compact_files(defer_index_remap=True)`` (Fragment Reuse Index — compaction and
index maintenance "no longer conflict", lance_docs/guide.md:3013) followed IMMEDIATELY by
``optimize_indices()`` — the exact shipped sequence in ``compact_one`` — must leave the dataset's
indices present and the data fully queryable. Drives the SHIPPED function on a real dataset (§0: test
the shipped composition, not a re-implementation), plus the error-prefix contract the sweep's FAIL
selection keys on (``open:`` vs ``maintain:``).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import lance
import pyarrow as pa
from compaction.services.optimize import compact_one


def _fragmented_indexed_dataset(root: Path) -> str:
    """A local Lance dataset with a BTREE index and several small fragments (each append = 1 fragment)."""
    uri = str(root / "t.lance")
    lance.write_dataset(pa.table({"id": pa.array(range(100), pa.int64())}), uri)
    ds = lance.dataset(uri)
    ds.create_scalar_index("id", "BTREE")
    for i in range(4):
        base = 100 + i * 10
        lance.write_dataset(
            pa.table({"id": pa.array(range(base, base + 10), pa.int64())}), uri, mode="append"
        )
    return uri


def test_compact_one_defer_index_remap_keeps_indices_working(tmp_path: Path) -> None:
    uri = _fragmented_indexed_dataset(tmp_path)
    assert len(lance.dataset(uri).get_fragments()) >= 5  # genuinely fragmented before the pass

    result = compact_one(uri, {}, older_than=timedelta(days=7))

    # The shipped sequence (deferred-remap compaction → immediate optimize_indices) completes cleanly …
    assert result.error is None, result.error
    assert result.fragments_removed >= 4  # the small fragments actually merged (into fewer, bigger ones)
    assert result.fragments_added < result.fragments_removed
    # EXACTLY the one user index: deferred remap creates the __lance_frag_reuse SYSTEM index, which the
    # metric must exclude (>=1 would stay green while the system index inflates every dataset's count).
    assert result.indices_optimized == 1
    # … and the dataset stays correct afterwards: the index is still listed and the data fully readable
    # (an index broken by the deferred remap would surface here as a wrong count or a scan error).
    ds = lance.dataset(uri)
    assert any(ix["fields"] == ["id"] for ix in ds.list_indices())
    assert ds.count_rows() == 140
    assert ds.count_rows(filter="id = 137") == 1  # a row from a post-index append is findable


def test_compact_one_reports_zero_indices_for_an_unindexed_dataset(tmp_path: Path) -> None:
    # Review 2026-07-10 (verified on pylance 8.0.0): defer_index_remap creates the __lance_frag_reuse
    # system index on first compaction — an unindexed dataset must still report indices_optimized == 0,
    # not phantom "index maintenance" on every tick forever after.
    uri = str(tmp_path / "plain.lance")
    lance.write_dataset(pa.table({"id": pa.array(range(50), pa.int64())}), uri)
    for i in range(3):
        lance.write_dataset(
            pa.table({"id": pa.array(range(50 + i * 10, 60 + i * 10), pa.int64())}), uri, mode="append"
        )

    result = compact_one(uri, {}, older_than=timedelta(days=7))

    assert result.error is None, result.error
    assert result.fragments_removed >= 3
    assert result.indices_optimized == 0  # the system index is excluded from the metric


def test_compact_one_open_error_prefix_for_a_missing_dataset(tmp_path: Path) -> None:
    # The sweep's FAIL selection keys on these prefixes: an unopenable dir is "open:" (transient
    # non-dataset noise → never a FAIL event). Pin the prefix so a reword can't silently flip selection.
    result = compact_one(str(tmp_path / "nope.lance"), {}, older_than=timedelta(days=7))
    assert result.error is not None and result.error.startswith("open:")
