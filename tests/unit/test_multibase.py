"""#3-B — Lance multi-base DATA distribution (unit).

The write path (`dataplane._write_blob`) is the only place multi-base touches Lance, so patch
`lance.write_dataset` and assert the base wiring (initial_bases + target_bases + base_store_params) — and,
critically, that the #5a invariant (2.2 + stable-row-ids) SURVIVES multi-base. Config allowlist parsing
mirrors the external-blob-bases property.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import lance
import pyarrow as pa
from catalog.core.config import Settings
from catalog.services import dataplane


def _table() -> pa.Table:
    return pa.table({"id": pa.array([1, 2], pa.int64())})


_SO = {"endpoint": "http://rf:9000", "access_key_id": "k", "secret_access_key": "s", "region": "us-east-1"}


def _capture_write() -> tuple[dict[str, Any], Any]:
    captured: dict[str, Any] = {}

    def fake_write(_table_obj: Any, _uri: str, **kw: Any) -> Any:
        captured.update(kw)
        return MagicMock(version=1)

    return captured, fake_write


def test_write_threads_data_bases_into_write_dataset() -> None:
    captured, fake_write = _capture_write()
    with patch.object(lance, "write_dataset", fake_write):
        dataplane._write_blob(
            _table(),
            "s3://root/tbl",
            _SO,
            mode="create",
            allow_external=False,
            external_blob_bases=[],
            data_bases=["s3://b1", "s3://b2/data"],
        )
    assert captured["initial_bases"] is not None and len(captured["initial_bases"]) == 2  # both registered
    assert captured["target_bases"] == ["b1", "b2-data"]  # round-robin targets, referenced by derived NAME
    assert set(captured["base_store_params"]) == {"s3://b1", "s3://b2/data"}  # per-base runtime creds
    # #5a invariant MUST survive multi-base (the whole point of routing creates through this 2.2 path):
    assert captured["enable_stable_row_ids"] is True
    assert captured["data_storage_version"] == "2.2"


def test_external_and_data_bases_compose() -> None:
    captured, fake_write = _capture_write()
    with patch.object(lance, "write_dataset", fake_write):
        dataplane._write_blob(
            _table(),
            "s3://root/tbl",
            _SO,
            mode="create",
            allow_external=False,
            external_blob_bases=["s3://media"],
            data_bases=["s3://b1"],
        )
    assert len(captured["initial_bases"]) == 2  # external-blob base + data base both registered
    assert captured["target_bases"] == ["b1"]  # only the DATA base is a write target


def test_empty_data_bases_is_backward_compatible() -> None:
    captured, fake_write = _capture_write()
    with patch.object(lance, "write_dataset", fake_write):
        dataplane._write_blob(
            _table(), "s3://root/tbl", _SO, mode="create", allow_external=False, external_blob_bases=[]
        )
    assert captured["initial_bases"] is None
    assert captured["target_bases"] is None
    assert captured["base_store_params"] is None
    assert captured["enable_stable_row_ids"] is True  # single-location create is still 2.2 + row-ids


def test_data_bases_are_create_only() -> None:
    captured, fake_write = _capture_write()
    with patch.object(lance, "write_dataset", fake_write):
        dataplane._write_blob(
            _table(),
            "s3://root/tbl",
            _SO,
            mode="overwrite",
            allow_external=False,
            external_blob_bases=[],
            data_bases=["s3://b1"],
        )
    # overwrite/append inherit the manifest's registered layout — initial_bases + target_bases are create-only
    assert captured["initial_bases"] is None
    assert captured["target_bases"] is None


def test_config_allowlist_parsing() -> None:
    s = Settings.model_validate(
        {"multibase_data_bases": "s3://b1, s3://b2 ,", "s3_access_key_id": "x", "s3_secret_access_key": "x"}
    )
    assert s.multibase_data_base_list == ["s3://b1", "s3://b2"]
    empty = Settings.model_validate({"s3_access_key_id": "x", "s3_secret_access_key": "x"})
    assert empty.multibase_data_base_list == []  # default off
