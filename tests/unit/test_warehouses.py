"""#3-A — warehouse registry, runtime bucket provisioning, and the admin FGA gate (unit).

The registry round-trips against a LOCAL filesystem root (``_fs_and_base`` falls back to the local FS for a
non-``s3://`` uri), so no object storage is needed here. Provisioning is boto3, mocked. The gate is driven
through the real ``require_can_create_warehouse`` resolver, and a separate test asserts the (type, relation)
it checks actually EXISTS in the compiled model (the mocked-``fga.check`` caveat: a mock pins the passed
string, not that the relation is defined on the type).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from catalog.api import fga_deps
from catalog.core.config import Settings
from catalog.services import warehouses
from common import fga as fga_module
from common.oidc import IDToken
from lance_namespace import PermissionDeniedError, ServiceUnavailableError


def _root(tmp_path: Any) -> str:
    return f"file://{tmp_path}"


# --------------------------------------------------------------------------- #
# registry round-trip
# --------------------------------------------------------------------------- #


def test_put_get_list_roundtrip(tmp_path: Any) -> None:
    root, so = _root(tmp_path), {}
    rec_a = {"id": "wh-a", "bucket": "bkt-a", "root_uri": "s3://bkt-a", "project": "acme", "created_at": "t"}
    rec_b = {"id": "wh-b", "bucket": "bkt-b", "root_uri": "s3://bkt-b", "project": "acme", "created_at": "t"}
    assert warehouses.get_warehouse(root, so, "wh-a") is None  # unregistered → None
    warehouses.put_warehouse(root, so, rec_a)
    warehouses.put_warehouse(root, so, rec_b)
    assert warehouses.get_warehouse(root, so, "wh-a") == rec_a
    assert {r["id"] for r in warehouses.list_warehouses(root, so)} == {"wh-a", "wh-b"}


def test_list_empty_registry_is_empty(tmp_path: Any) -> None:
    assert warehouses.list_warehouses(_root(tmp_path), {}) == []


def test_bind_and_resolve(tmp_path: Any) -> None:
    root, so = _root(tmp_path), {}
    assert warehouses.warehouse_for_namespace(root, so, "team_ns") is None  # unbound → default root
    warehouses.bind_namespace(root, so, "team_ns", "wh-a", "s3://bkt-a")
    assert warehouses.warehouse_for_namespace(root, so, "team_ns") == "s3://bkt-a"


# --------------------------------------------------------------------------- #
# provisioning (idempotent, like `mc mb --ignore-existing`)
# --------------------------------------------------------------------------- #

_SO = {"endpoint": "http://rustfs:9000", "access_key_id": "k", "secret_access_key": "s", "region": "us-1"}


def test_provision_creates_bucket() -> None:
    fake = MagicMock()
    with patch("boto3.client", return_value=fake):
        warehouses.provision_bucket("bkt-a", _SO)
    fake.create_bucket.assert_called_once_with(Bucket="bkt-a")


@pytest.mark.parametrize("code", ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"])
def test_provision_idempotent_on_existing(code: str) -> None:
    fake = MagicMock()
    fake.create_bucket.side_effect = ClientError({"Error": {"Code": code}}, "CreateBucket")
    with patch("boto3.client", return_value=fake):
        warehouses.provision_bucket("bkt-a", _SO)  # must NOT raise — a re-provision is a no-op


def test_provision_reraises_real_errors() -> None:
    fake = MagicMock()
    fake.create_bucket.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "CreateBucket")
    with patch("boto3.client", return_value=fake), pytest.raises(ClientError):
        warehouses.provision_bucket("bkt-a", _SO)


# --------------------------------------------------------------------------- #
# the admin gate — driven through the REAL resolver
# --------------------------------------------------------------------------- #


def _fga_settings() -> Settings:
    return Settings.model_validate(
        {
            "fga_enabled": True,
            "oidc_enabled": True,
            "oidc_issuer": "https://idp",
            "oidc_audience": "lance",
            "s3_access_key_id": "x",
            "s3_secret_access_key": "x",
        }
    )


_TOKEN = IDToken(iss="i", sub="alice", aud="lance", exp=1, iat=1)


def test_gate_checks_can_create_warehouse_on_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str, str]] = []

    async def fake_check(_c: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        captured.append((user, relation, obj))
        return True

    monkeypatch.setattr(fga_module, "check", fake_check)
    asyncio.run(
        fga_deps.require_can_create_warehouse(MagicMock(), _fga_settings(), _TOKEN, project="acme")
    )
    # The gate must check the DORMANT project-admin action on the PROJECT, not a table/namespace relation.
    assert captured == [("alice", "can_create_warehouse", "project:acme")]


def test_gate_denies_with_403(monkeypatch: pytest.MonkeyPatch) -> None:
    async def deny(_c: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        return False

    monkeypatch.setattr(fga_module, "check", deny)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(
            fga_deps.require_can_create_warehouse(MagicMock(), _fga_settings(), _TOKEN, project="acme")
        )


def test_gate_fails_closed_on_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def outage(_c: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        raise ServiceUnavailableError("openfga down")

    monkeypatch.setattr(fga_module, "check", outage)
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga_deps.require_can_create_warehouse(MagicMock(), _fga_settings(), _TOKEN, project="acme")
        )


def test_gate_noop_when_fga_off() -> None:
    off = Settings.model_validate({"s3_access_key_id": "x", "s3_secret_access_key": "x"})
    asyncio.run(fga_deps.require_can_create_warehouse(None, off, None, project="acme"))  # no raise, no client


def test_model_actually_defines_the_warehouse_relations() -> None:
    # The mocked-fga caveat: a mock pins the STRING, not that the relation EXISTS on the type. Assert the
    # (type, relation) pairs this feature checks are really in the compiled model, so a phantom relation
    # (which OpenFGA rejects with a 400 → fail-closed 503 for every caller) is caught here, not in prod.
    model = fga_module.load_model()
    defined = {
        (t["type"], rel)
        for t in model["type_definitions"]
        for rel in (t.get("relations") or {})
    }
    assert ("project", "can_create_warehouse") in defined
    assert ("warehouse", "can_get_metadata") in defined
    assert ("warehouse", "can_create_namespace") in defined


def test_seed_warehouse_writes_only_relations_the_model_defines(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression guard for a WRITE-side model mismatch the mocked-`fga.check` gate tests cannot catch: the
    # seed originally wrote `warehouse#parent` (via grant_on_create) but the warehouse type's parent-pointer
    # is `project`, not `parent` — OpenFGA rejects the undefined relation and the whole seed 503s LIVE while
    # every unit test stays green. Drive the REAL seed with a recording `write_tuples` and assert every
    # (type, relation) it emits is actually defined in the compiled model.json.
    captured: list[Any] = []

    async def rec_write(_client: object, tuples: list[Any], **_kw: object) -> None:
        captured.extend(tuples)

    monkeypatch.setattr(fga_module, "write_tuples", rec_write)
    asyncio.run(
        fga_deps.seed_warehouse(MagicMock(), _fga_settings(), _TOKEN, warehouse_id="wh-a", project="acme")
    )
    assert captured, "seed_warehouse wrote no tuples"
    model = {t["type"]: set(t.get("relations") or {}) for t in fga_module.load_model()["type_definitions"]}
    for t in captured:
        obj_type = t.object.split(":", 1)[0]
        assert t.relation in model.get(obj_type, set()), (
            f"seed_warehouse writes {obj_type}#{t.relation}, NOT a relation on the compiled model — OpenFGA "
            f"would reject the seed (503). {obj_type} has: {sorted(model.get(obj_type, set()))}"
        )
    written = {(t.object.split(":", 1)[0], t.relation) for t in captured}
    assert ("warehouse", "project") in written  # the parent link uses the warehouse's real pointer relation
    assert ("warehouse", "parent") not in written  # ...never the namespace/table `parent` name (the old bug)
