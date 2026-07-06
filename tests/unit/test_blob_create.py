"""§9 blob-v2 create path — detection helpers + the catalog's ``create_table`` facade.

The facade tests run a real ``dir`` namespace + real pylance write (no mocks): they are the unit-level
proof that a blob column, which the native create rejects at 2.1, round-trips at file format 2.2, that a
plain schema still takes the native 2.1 path, and that the create ``mode`` (Create/ExistOk/Overwrite) is
honoured on the blob path.
"""

from __future__ import annotations

from pathlib import Path

import lance
import pyarrow as pa
import pytest
from catalog.services.dataplane import _schema_is_blob, create_table
from common import blobs
from lance import Blob, blob_array, blob_field
from lance_namespace import (
    DeclareTableRequest,
    DescribeTableRequest,
    InvalidInputError,
    TableAlreadyExistsError,
    connect,
)


def _blob_schema() -> pa.Schema:
    return pa.schema([pa.field("id", pa.int64()), blob_field("payload"), pa.field("src", pa.string())])


def _blob_ipc(payloads: list[bytes] | None = None) -> bytes:
    payloads = payloads or [b"img-1", b"video" * 1000]
    ids = list(range(len(payloads)))
    table = pa.table(
        {"id": ids, "payload": blob_array(payloads), "src": ["cam"] * len(payloads)},
        schema=_blob_schema(),
    )
    return _ipc(table)


def _ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _open(ns, segments: list[str]) -> lance.LanceDataset:
    described = ns.describe_table(
        DescribeTableRequest(id=segments, with_table_uri=True, load_detailed_metadata=True)
    )
    return lance.dataset(described.table_uri or described.location)


# --- detection helpers ----------------------------------------------------- #


def test_is_blob_field_detects_blob_v2_and_ignores_scalars() -> None:
    schema = _blob_schema()
    assert blobs.is_blob_field(schema.field("payload"))
    assert not blobs.is_blob_field(schema.field("id"))
    assert not blobs.is_blob_field(schema.field("src"))


def test_schema_has_blob_and_blob_field_names() -> None:
    assert blobs.schema_has_blob(_blob_schema())
    assert blobs.blob_field_names(_blob_schema()) == ["payload"]
    plain = pa.schema([pa.field("id", pa.int64())])
    assert not blobs.schema_has_blob(plain)
    assert blobs.blob_field_names(plain) == []


def test_schema_is_blob_over_ipc_and_garbage() -> None:
    assert _schema_is_blob(_blob_ipc()) is True
    assert _schema_is_blob(_ipc(pa.table({"id": [1]}))) is False
    assert _schema_is_blob(b"not-an-arrow-stream") is False  # unparseable → native path, not a crash


# --- the create_table facade (real dir namespace + real pylance) ----------- #


def test_create_table_writes_blob_at_2_2_and_roundtrips(tmp_path: Path) -> None:
    ns = connect("dir", {"root": str(tmp_path)})
    resp = create_table(ns, {}, ["clips"], _blob_ipc(), mode="create")

    assert resp.location
    dataset = _open(ns, ["clips"])
    assert dataset.data_storage_version == "2.2"
    assert dataset.count_rows() == 2
    assert dataset.read_blobs("payload", indices=[0])[0][1] == b"img-1"


def test_create_table_routes_plain_schema_to_native_2_1(tmp_path: Path) -> None:
    ns = connect("dir", {"root": str(tmp_path)})
    create_table(ns, {}, ["plain"], _ipc(pa.table({"id": [1, 2, 3]})), mode="create")

    dataset = _open(ns, ["plain"])
    assert dataset.data_storage_version == "2.1"  # native default — no blob, no 2.2
    assert dataset.count_rows() == 3


def test_create_mode_conflicts_when_blob_table_exists(tmp_path: Path) -> None:
    ns = connect("dir", {"root": str(tmp_path)})
    create_table(ns, {}, ["c1"], _blob_ipc(), mode="create")
    with pytest.raises(TableAlreadyExistsError):
        create_table(ns, {}, ["c1"], _blob_ipc(), mode="create")


def test_overwrite_replaces_existing_blob_table(tmp_path: Path) -> None:
    ns = connect("dir", {"root": str(tmp_path)})
    create_table(ns, {}, ["o1"], _blob_ipc([b"a", b"b", b"c"]), mode="create")
    resp = create_table(ns, {}, ["o1"], _blob_ipc([b"z"]), mode="overwrite")

    dataset = _open(ns, ["o1"])
    assert dataset.count_rows() == 1  # replaced 3 rows with 1
    assert dataset.read_blobs("payload", indices=[0])[0][1] == b"z"
    assert resp.version is not None and resp.version > 1  # overwrite committed a new version


def test_exist_ok_keeps_existing_blob_table(tmp_path: Path) -> None:
    ns = connect("dir", {"root": str(tmp_path)})
    create_table(ns, {}, ["e1"], _blob_ipc([b"a", b"b"]), mode="create")
    second = create_table(ns, {}, ["e1"], _blob_ipc([b"z"]), mode="exist_ok")

    # ExistOk keeps the existing table untouched — the 1-row payload is NOT written over the original 2.
    assert second.location
    dataset = _open(ns, ["e1"])
    assert dataset.count_rows() == 2
    assert dataset.read_blobs("payload", indices=[0])[0][1] == b"a"


# --- declared-only tables (POST /declare, and this path's own crash-rollback leaves one) ----------- #


def test_exist_ok_on_declared_only_table_writes_instead_of_500(tmp_path: Path) -> None:
    # A declared-but-unwritten table has NO readable dataset. Opening it to read `.version` (the pre-fix
    # ExistOk path) would raise -> 500. ExistOk must instead land the first data version into that location.
    ns = connect("dir", {"root": str(tmp_path)})
    ns.declare_table(DeclareTableRequest(id=["d1"]))

    resp = create_table(ns, {}, ["d1"], _blob_ipc([b"first"]), mode="exist_ok")

    assert resp.location
    dataset = _open(ns, ["d1"])
    assert dataset.data_storage_version == "2.2"
    assert dataset.count_rows() == 1
    assert dataset.read_blobs("payload", indices=[0])[0][1] == b"first"


def test_default_create_on_declared_only_table_writes_the_first_version(tmp_path: Path) -> None:
    # declare → crash → retry with the default mode must converge to a written table, not conflict on the
    # existing declare. (Same path a failed fresh write's rollback intentionally does NOT leave — but a
    # separate POST /declare does.)
    ns = connect("dir", {"root": str(tmp_path)})
    ns.declare_table(DeclareTableRequest(id=["d2"]))

    create_table(ns, {}, ["d2"], _blob_ipc([b"a", b"b"]), mode="create")

    dataset = _open(ns, ["d2"])
    assert dataset.count_rows() == 2
    assert dataset.read_blobs("payload", indices=[0])[0][1] == b"a"


# --- blob modes: managed (inline/packed/dedicated) always; external pointer gated ------------------ #


def test_managed_blob_modes_inline_and_dedicated(tmp_path: Path) -> None:
    # Managed blobs (bytes copied in) work regardless of the flag: small → inline, large → dedicated sidecar.
    ns = connect("dir", {"root": str(tmp_path)})
    small, large = b"tiny-inline", b"x" * 3_000_000
    schema = pa.schema([pa.field("id", pa.int64()), blob_field("blob")])

    table = pa.table({"id": [1, 2], "blob": blob_array([small, large])}, schema=schema)
    create_table(ns, {}, ["managed"], _ipc(table))

    ds = _open(ns, ["managed"])
    assert ds.data_storage_version == "2.2"
    assert ds.read_blobs("blob", indices=[0])[0][1] == small
    assert ds.read_blobs("blob", indices=[1])[0][1] == large


def test_external_pointer_blob_is_gated_by_the_flag(tmp_path: Path) -> None:
    source = tmp_path / "external.bin"
    source.write_bytes(b"external-bytes-payload")
    ns = connect("dir", {"root": str(tmp_path / "root")})
    schema = pa.schema([pa.field("id", pa.int64()), blob_field("blob")])
    pointer = pa.table(
        {"id": [1], "blob": blob_array([Blob.from_uri(source.as_uri(), position=0, size=8)])},
        schema=schema,
    )
    data = _ipc(pointer)

    # Default: an external pointer outside the dataset root is rejected as a clean client error (400).
    with pytest.raises(InvalidInputError, match="external"):
        create_table(ns, {}, ["ext_off"], data)

    # Opted in: accepted, written at 2.2, and the referenced byte slice reads back.
    create_table(ns, {}, ["ext_on"], data, allow_external_blobs=True)
    ds = _open(ns, ["ext_on"])
    assert ds.data_storage_version == "2.2"
    assert ds.read_blobs("blob", indices=[0])[0][1] == b"external"  # first 8 bytes of the source


def test_external_blob_allowlist_accepts_in_base_rejects_out_of_base(tmp_path: Path) -> None:
    """#92: the SAFER posture. With a registered base allowlist and the blanket flag OFF, an external
    Blob.from_uri UNDER a registered base is accepted, while one OUTSIDE every registered base is rejected —
    a curated media bucket without opening the blanket outside-bases door."""
    base = tmp_path / "approved"
    base.mkdir()
    (base / "obj.bin").write_bytes(b"approved-external-payload")
    outside = tmp_path / "elsewhere.bin"
    outside.write_bytes(b"unapproved-payload")
    ns = connect("dir", {"root": str(tmp_path / "root")})
    schema = pa.schema([pa.field("id", pa.int64()), blob_field("blob")])

    def _pointer(uri: str) -> bytes:
        return _ipc(
            pa.table({"id": [1], "blob": blob_array([Blob.from_uri(uri, position=0, size=8)])}, schema=schema)
        )

    bases = [base.as_uri()]
    # UNDER the registered base → accepted with allow_external_blobs left False.
    create_table(ns, {}, ["in_base"], _pointer((base / "obj.bin").as_uri()), external_blob_bases=bases)
    ds = _open(ns, ["in_base"])
    assert ds.data_storage_version == "2.2"
    assert ds.read_blobs("blob", indices=[0])[0][1] == b"approved"  # first 8 bytes, read back

    # OUTSIDE every registered base → rejected (allowlist doesn't cover it, blanket flag off).
    with pytest.raises(InvalidInputError, match="external"):
        create_table(ns, {}, ["out_base"], _pointer(outside.as_uri()), external_blob_bases=bases)


def test_rejected_external_create_rolls_back_and_stays_retryable(tmp_path: Path) -> None:
    source = tmp_path / "external.bin"
    source.write_bytes(b"external-bytes")
    ns = connect("dir", {"root": str(tmp_path / "root")})
    schema = pa.schema([pa.field("id", pa.int64()), blob_field("blob")])
    pointer = _ipc(
        pa.table(
            {"id": [1], "blob": blob_array([Blob.from_uri(source.as_uri(), position=0, size=8)])},
            schema=schema,
        )
    )

    with pytest.raises(InvalidInputError):
        create_table(ns, {}, ["rb"], pointer)  # flag off → rejected, declared table rolled back

    # retryable: the name is free (rollback dropped the declare), so a managed create at the same id succeeds
    create_table(ns, {}, ["rb"], _ipc(pa.table({"id": [1], "blob": blob_array([b"managed"])}, schema=schema)))
    assert _open(ns, ["rb"]).read_blobs("blob", indices=[0])[0][1] == b"managed"
