"""Unit tests for embedding lineage coordinates into the Lance file (#21, ``app.core.lineage_metadata``).

The round-trip tests prove the coordinates land in the Arrow schema metadata; the Lance test proves
they survive a real ``write_dataset`` → ``dataset`` cycle (i.e. the data is genuinely self-describing).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from app.core.lineage_metadata import build_lineage_metadata, inject_into_arrow_stream


def _stream(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _schema_meta(stream: bytes) -> dict[str, str]:
    schema = pa.ipc.open_stream(stream).read_all().schema
    return {k.decode(): v.decode() for k, v in (schema.metadata or {}).items()}


def test_build_lineage_metadata() -> None:
    md = build_lineage_metadata(table_id="a$b$c", namespace="a$b", run_id="r-1", created_by="alice")
    assert md == {
        "lineage.dataset_id": "a$b$c",
        "lineage.namespace": "a$b",
        "lineage.create_run_id": "r-1",
        "lineage.created_by": "alice",
    }


def test_build_lineage_metadata_none_author_becomes_empty() -> None:
    md = build_lineage_metadata(table_id="t", namespace="", run_id="r", created_by=None)
    assert md["lineage.created_by"] == ""


def test_inject_into_arrow_stream_roundtrip() -> None:
    table = pa.table({"id": [1, 2, 3], "payload_src": ["a", "b", "a"]})
    md = build_lineage_metadata(table_id="a$b$c", namespace="a$b", run_id="r-1", created_by="alice")
    out = inject_into_arrow_stream(_stream(table), md)
    got = pa.ipc.open_stream(out).read_all()
    assert got.column("id").to_pylist() == [1, 2, 3]  # data preserved
    assert got.column("payload_src").to_pylist() == ["a", "b", "a"]
    meta = _schema_meta(out)
    assert meta["lineage.dataset_id"] == "a$b$c"
    assert meta["lineage.create_run_id"] == "r-1"
    assert meta["lineage.created_by"] == "alice"


def test_inject_preserves_existing_schema_metadata() -> None:
    schema = pa.schema([("id", pa.int64())], metadata={"existing": "keep"})
    table = pa.table({"id": [1]}, schema=schema)
    out = inject_into_arrow_stream(
        _stream(table), build_lineage_metadata(table_id="t", namespace="", run_id="r", created_by=None)
    )
    meta = _schema_meta(out)
    assert meta["existing"] == "keep"  # pre-existing schema metadata is preserved
    assert meta["lineage.dataset_id"] == "t"


def test_injected_metadata_persists_in_lance_file(tmp_path: Path) -> None:
    """The coordinates must survive a real Lance write → read (the whole point of #21)."""
    import lance

    table = pa.table({"id": [1, 2]})
    md = build_lineage_metadata(table_id="a$b$c", namespace="a$b", run_id="r-9", created_by="alice")
    got = pa.ipc.open_stream(inject_into_arrow_stream(_stream(table), md)).read_all()

    uri = str(tmp_path / "t.lance")
    lance.write_dataset(got, uri)
    schema = lance.dataset(uri).schema
    meta = {k.decode(): v.decode() for k, v in (schema.metadata or {}).items()}
    assert meta["lineage.dataset_id"] == "a$b$c"
    assert meta["lineage.create_run_id"] == "r-9"
    assert meta["lineage.created_by"] == "alice"
