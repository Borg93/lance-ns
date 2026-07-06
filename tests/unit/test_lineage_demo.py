"""Behavioral tests for the demo data-peek router (§7) — real Lance reads, no S3/AGE.

``_read_dataset`` / ``_read_lineage_jsonb`` do the actual work (the route just maps the
medallion layout over them); lance reads a local path exactly like ``s3://``, so the
per-version schema walk, the row/version counts, and gold's embedded JSONB round-trip are
all provable infra-free. Playwright mocks this router empty — this is its only behavioral net.
"""

from __future__ import annotations

import json
from pathlib import Path

import lance
import pyarrow as pa
from lineage.api.v1.endpoints.demo import _read_dataset, _read_lineage_jsonb


def test_read_dataset_absent_is_exists_false(tmp_path: Path) -> None:
    result = _read_dataset("bronze$events", str(tmp_path / "missing.lance"), {})
    assert result.exists is False
    assert result.current_version is None and result.versions == []


def test_read_dataset_walks_schema_per_version(tmp_path: Path) -> None:
    """The demo peek shows WHAT CHANGED in storage: each Lance version carries its own schema,
    so a column added in v2 appears only from v2 on — plus the live row count and version head."""
    uri = str(tmp_path / "features.lance")
    lance.write_dataset(pa.table({"id": pa.array([1, 2], pa.int64())}), uri)
    ds = lance.dataset(uri)
    ds.add_columns({"score": "cast(id * 2 as double)"})  # schema evolution → v2

    result = _read_dataset("silver$features", uri, {})

    assert result.exists is True
    assert result.current_version == 2
    assert result.row_count == 2
    by_version = {v.version: [f.name for f in v.fields] for v in result.versions}
    assert by_version[1] == ["id"]
    assert by_version[2] == ["id", "score"]
    types = {f.name: f.type for v in result.versions for f in v.fields}
    assert types == {"id": "int64", "score": "double"}  # type_label passthrough for plain types
    assert result.lineage_jsonb is None  # only gold carries the embedded lineage


def test_read_dataset_gold_embeds_lineage_jsonb(tmp_path: Path) -> None:
    """gold$catalog rows embed their lineage as a JSON string column — the peek parses it back."""
    uri = str(tmp_path / "catalog.lance")
    lineage_doc = {"upstream": ["silver$features"], "run": "tok123"}
    lance.write_dataset(
        pa.table({"id": pa.array([1], pa.int64()), "lineage": pa.array([json.dumps(lineage_doc)])}),
        uri,
    )

    result = _read_dataset("gold$catalog", uri, {})

    assert result.lineage_jsonb == lineage_doc


def test_read_lineage_jsonb_degrades_to_none() -> None:
    """Column absent, empty, or non-JSON → None, never a 500 (demo peek is best-effort)."""

    class _NoColumn:
        def to_table(self, columns: list[str]) -> pa.Table:
            raise KeyError(columns[0])

    assert _read_lineage_jsonb(_NoColumn()) is None

    class _Empty:
        def to_table(self, columns: list[str]) -> pa.Table:  # noqa: ARG002
            return pa.table({"lineage": pa.array([], pa.string())})

    assert _read_lineage_jsonb(_Empty()) is None

    class _Garbage:
        def to_table(self, columns: list[str]) -> pa.Table:  # noqa: ARG002
            return pa.table({"lineage": pa.array(["not json"])})

    assert _read_lineage_jsonb(_Garbage()) is None
