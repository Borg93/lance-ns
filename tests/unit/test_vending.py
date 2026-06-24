"""Unit tests for the pluggable credential vendor (app.core.vending).

No network: the STS path is exercised with an injected fake ``assume_role`` so
the session-policy scoping + storage_options assembly are pinned without boto3.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.core.vending import (
    ModeBVendor,
    StaticPrefixVendor,
    StsVendor,
    build_session_policy,
    make_vendor,
    split_s3_location,
)


def test_split_s3_location() -> None:
    assert split_s3_location("s3://bucket/a/b/c") == ("bucket", "a/b/c")
    assert split_s3_location("s3://bucket") == ("bucket", "")
    with pytest.raises(ValueError):
        split_s3_location("/no/bucket")


def test_build_session_policy_read_vs_write() -> None:
    read: Any = build_session_policy("bkt", "tables/db1$users", "read")
    write: Any = build_session_policy("bkt", "tables/db1$users", "write")
    read_objs = read["Statement"][1]
    write_objs = write["Statement"][1]
    assert "s3:GetObject" in read_objs["Action"]
    assert "s3:PutObject" not in read_objs["Action"]
    assert "s3:PutObject" in write_objs["Action"]
    assert "s3:DeleteObject" in write_objs["Action"]
    # object actions scoped to exactly the table prefix
    assert read_objs["Resource"] == "arn:aws:s3:::bkt/tables/db1$users/*"
    list_stmt = read["Statement"][0]
    assert list_stmt["Condition"]["StringLike"]["s3:prefix"] == ["tables/db1$users/*"]


def test_build_session_policy_root_prefix() -> None:
    pol: Any = build_session_policy("bkt", "", "read")
    assert pol["Statement"][1]["Resource"] == "arn:aws:s3:::bkt/*"
    assert pol["Statement"][0]["Condition"]["StringLike"]["s3:prefix"] == ["*"]


def test_mode_b_vendor_returns_none() -> None:
    assert ModeBVendor().vend(table_location="s3://b/t", tier="read") is None


def test_static_prefix_vendor() -> None:
    vendor = StaticPrefixVendor({"b": {"access_key_id": "AK", "secret_access_key": "SK"}})
    out = vendor.vend(table_location="s3://b/t", tier="write")
    assert out is not None
    assert out.storage_options["access_key_id"] == "AK"
    assert out.expires_at_millis is None
    # unknown bucket -> None (caller falls back to Mode B)
    assert vendor.vend(table_location="s3://other/t", tier="read") is None


def test_sts_vendor_with_fake_assume_role() -> None:
    captured: dict[str, Any] = {}

    def fake_assume_role(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "AK",
                "SecretAccessKey": "SK",
                "SessionToken": "TK",
                "Expiration": dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
            }
        }

    vendor = StsVendor(
        role_arn="arn:aws:iam::1:role/r",
        region="us-east-1",
        endpoint="http://minio:9000",
        ttl_seconds=900,
        assume_role=fake_assume_role,
    )
    out = vendor.vend(table_location="s3://bkt/tables/t1", tier="write")
    assert out is not None
    opts = out.storage_options
    assert opts["access_key_id"] == "AK"
    assert opts["secret_access_key"] == "SK"
    assert opts["session_token"] == "TK"
    assert opts["endpoint"] == "http://minio:9000"
    assert out.expires_at_millis is not None and out.expires_at_millis > 0
    # the inline session policy was passed, scoped to the table prefix + write actions
    assert captured["DurationSeconds"] == 900
    assert "tables/t1" in captured["Policy"]
    assert "s3:PutObject" in captured["Policy"]


def test_make_vendor_selection() -> None:
    assert isinstance(make_vendor("mode_b"), ModeBVendor)
    assert isinstance(make_vendor("static"), StaticPrefixVendor)
    assert isinstance(make_vendor("sts", assume_role_arn="arn:aws:iam::1:role/r"), StsVendor)


def test_make_vendor_sts_requires_arn() -> None:
    with pytest.raises(ValueError):
        make_vendor("sts")
