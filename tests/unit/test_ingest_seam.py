"""Provider-agnostic ingest/egress seam + bronze source-URI provenance (deliverable 3)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import lance
import pyarrow.fs as pafs
import pytest
from common.sinks import LocalDirSink, S3Sink
from common.sources import LocalDirSource, S3Source
from medallion.services.ingest import ingest_to_bronze
from PIL import Image


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def test_local_dir_source_recurses_sorted_and_yields_file_uris(tmp_path: Path) -> None:
    (tmp_path / "b.png").write_bytes(b"BBB")  # written first, but must sort AFTER a.png
    (tmp_path / "a.png").write_bytes(b"AAA")
    (tmp_path / "skip.txt").write_bytes(b"no")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.png").write_bytes(b"CCC")  # nested — proves rglob recursion

    objects = list(LocalDirSource(tmp_path, "*.png").iter_objects())

    assert [obj.data for obj in objects] == [b"AAA", b"BBB", b"CCC"]  # sorted, recursive, skip.txt excluded
    assert all(obj.uri.startswith("file://") and obj.uri.endswith(".png") for obj in objects)


def test_local_dir_sink_writes_and_returns_uri(tmp_path: Path) -> None:
    uri = LocalDirSink(tmp_path).put("out/thumb.png", b"PNGBYTES")

    assert uri.startswith("file://") and uri.endswith("out/thumb.png")
    assert (tmp_path / "out" / "thumb.png").read_bytes() == b"PNGBYTES"


def test_ingest_to_bronze_writes_2_2_blob_table_with_provenance(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_png(source_dir / "img1.png", (200, 0, 0))
    _write_png(source_dir / "img2.png", (0, 0, 200))
    bronze = str(tmp_path / "bronze")

    result = ingest_to_bronze(LocalDirSource(source_dir, "*.png"), bronze, {})

    ds = lance.dataset(bronze)
    assert ds.data_storage_version == "2.2"
    assert ds.has_stable_row_ids  # durable _rowid across compaction (create-time-only; forward-proofing)
    assert result.row_count == 2
    assert len(result.source_uris) == 2 and all(u.startswith("file://") for u in result.source_uris)
    # the blob-aware schema facet + the provenance column both ride the WROTE edge
    assert {"name": "payload", "type": "blob"} in result.fields
    assert {"name": "source_uri", "type": "string"} in result.fields
    # a real PNG round-trips through the managed blob, and the source URI is carried in the data
    assert ds.read_blobs("payload", indices=[0])[0][1][:4] == b"\x89PNG"
    assert ds.to_table(columns=["source_uri"]).column("source_uri")[0].as_py().startswith("file://")


def test_ingest_to_bronze_rejects_empty_source(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    # a mis-set prefix must fail loudly, not write a 0-row bronze and report a false success
    with pytest.raises(ValueError, match="no objects"):
        ingest_to_bronze(LocalDirSource(empty, "*.png"), str(tmp_path / "bronze"), {})


class _ReadStream:
    """pyarrow ``open_input_stream`` stand-in: a ``with``-usable reader exposing ``readall()``."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> _ReadStream:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def readall(self) -> bytes:
        return self._data


class _WriteStream:
    """pyarrow ``open_output_stream`` stand-in: buffers writes, commits them to the fs dict on close."""

    def __init__(self, files: dict[str, bytes], path: str) -> None:
        self._files = files
        self._path = path
        self._buffer = bytearray()

    def __enter__(self) -> _WriteStream:
        return self

    def __exit__(self, *_: object) -> bool:
        self._files[self._path] = bytes(self._buffer)
        return False

    def write(self, data: bytes) -> None:
        self._buffer.extend(data)


class _FakeFs:
    """The narrow slice of ``pyarrow.fs.FileSystem`` the S3 adapters touch, backed by an in-memory dict.

    Lets us exercise the adapters' own logic — recursive file filtering, ``bucket/prefix/key`` joining,
    ``s3://`` URI formation, byte round-trip — with no live S3 (that path is covered by the live e2e).
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def get_file_info(self, selector: pafs.FileSelector) -> list[pafs.FileInfo]:
        base = selector.base_dir.rstrip("/") + "/"
        infos: list[pafs.FileInfo] = []
        seen_dirs: set[str] = set()
        # Iterate in dict (insertion) order — deliberately NOT sorted, so the test proves S3Source sorts.
        for path in self.files:
            if not path.startswith(base):
                continue
            # Emit the intermediate common-prefix "directory" entries a recursive S3 listing returns, so the
            # adapter's `if info.type != File: continue` branch is actually exercised (not dead in-test).
            prefix = base
            for part in path[len(base) :].split("/")[:-1]:
                prefix = f"{prefix}{part}/"
                directory = prefix.rstrip("/")
                if directory not in seen_dirs:
                    seen_dirs.add(directory)
                    infos.append(pafs.FileInfo(directory, pafs.FileType.Directory))
            infos.append(pafs.FileInfo(path, pafs.FileType.File))
        return infos

    def open_input_stream(self, path: str) -> _ReadStream:
        return _ReadStream(self.files[path])

    def open_output_stream(self, path: str) -> _WriteStream:
        return _WriteStream(self.files, path)


def test_s3_source_yields_files_sorted_recursive_prefix_scoped() -> None:
    fs = _FakeFs(
        {
            "bucket/prefix/b.png": b"BBB",  # listed first, but must sort AFTER a.png
            "bucket/prefix/a.png": b"AAA",
            "bucket/prefix/nested/c.png": b"CCC",  # recursive + emits a "nested" directory entry to skip
            "bucket/other/d.png": b"DDD",  # outside the prefix — must not be yielded
        }
    )
    source = S3Source(cast(pafs.S3FileSystem, fs), "bucket", "prefix")

    objects = list(source.iter_objects())

    # sorted (a before b despite listing order), recursive (nested/c), dir-filtered, prefix-scoped (no d)
    assert [obj.data for obj in objects] == [b"AAA", b"BBB", b"CCC"]
    assert [obj.uri for obj in objects] == [
        "s3://bucket/prefix/a.png",
        "s3://bucket/prefix/b.png",
        "s3://bucket/prefix/nested/c.png",
    ]


def test_s3_sink_writes_key_under_prefix_and_returns_s3_uri() -> None:
    fs = _FakeFs({})
    uri = S3Sink(cast(pafs.S3FileSystem, fs), "bucket", "prefix").put("out/gold.arrow", b"BYTES")

    assert uri == "s3://bucket/prefix/out/gold.arrow"
    assert fs.files["bucket/prefix/out/gold.arrow"] == b"BYTES"


def test_s3_sink_empty_prefix_has_no_double_slash() -> None:
    # an unset prefix must not leave a `bucket//key` seam (the reason the old .replace("//","/") existed)
    uri = S3Sink(cast(pafs.S3FileSystem, _FakeFs({})), "bucket", "").put("gold.arrow", b"X")

    assert uri == "s3://bucket/gold.arrow"
