"""#3-A — the warehouse admin control-plane API over the app (our layer only; boto3 provision mocked).

Reuses the shared ``client`` fixture (mocked namespace backend). ``control_root`` points at a LOCAL temp
dir so the registry round-trips on the local FS with no object storage. Covers: create → list → get
(feature on, FGA off); the 501 when the feature is disabled; and the admin gate (FGA on) denying a
non-project-admin with 403.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from catalog.core.config import Settings, get_settings
from catalog.services import warehouses as wh_svc
from common import fga as fga_module
from common.oidc import IDToken
from fastapi.testclient import TestClient


def _settings(tmp_path: Any, *, enabled: bool = True, fga: bool = False) -> Settings:
    data: dict[str, Any] = {
        "impl": "dir",
        "root": "s3://lance-catalog",
        "warehouses_enabled": enabled,
        "control_root": f"file://{tmp_path}",
        "s3_access_key_id": "x",
        "s3_secret_access_key": "x",
    }
    if fga:
        data.update(
            {
                "fga_enabled": True,
                "oidc_enabled": True,
                "oidc_issuer": "https://idp",
                "oidc_audience": "lance",
            }
        )
    return Settings.model_validate(data)


def test_create_list_get_warehouse(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provisioned: list[str] = []
    monkeypatch.setattr(wh_svc, "provision_bucket", lambda bucket, so: provisioned.append(bucket))
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)

    resp = client.post("/v1/warehouses", json={"id": "wh-a", "project": "acme"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "wh-a" and body["bucket"] == "wh-a" and body["root_uri"] == "s3://wh-a"
    assert provisioned == ["wh-a"]  # the physical bucket was provisioned at runtime

    listed = client.get("/v1/warehouses")
    assert listed.status_code == 200
    assert "wh-a" in [w["id"] for w in listed.json()]

    got = client.get("/v1/warehouses/wh-a")
    assert got.status_code == 200 and got.json()["bucket"] == "wh-a"


def test_explicit_bucket_name(client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wh_svc, "provision_bucket", lambda bucket, so: None)
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    resp = client.post("/v1/warehouses", json={"id": "wh-b", "project": "acme", "bucket": "tenant-b-data"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["root_uri"] == "s3://tenant-b-data"


def test_get_missing_warehouse_404(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    assert client.get("/v1/warehouses/nope").status_code == 404


def test_invalid_id_rejected_400(client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wh_svc, "provision_bucket", lambda bucket, so: None)
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    # Uppercase + underscore is not a DNS-safe bucket fragment → 400 (never a malformed bucket create).
    assert client.post("/v1/warehouses", json={"id": "Bad_Name", "project": "acme"}).status_code == 400


def test_disabled_returns_501(client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path, enabled=False)
    assert client.post("/v1/warehouses", json={"id": "wh-x", "project": "acme"}).status_code == 501


def test_create_denied_for_non_admin_403(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.dependency_overrides[get_settings] = lambda: _settings(tmp_path, fga=True)
    verifier = MagicMock()
    verifier.verify.return_value = IDToken(iss="i", sub="mallory", aud="lance", exp=1, iat=1)
    client.app.state.oidc = verifier
    fga_client = MagicMock()
    fga_client.close = AsyncMock()
    client.app.state.fga = fga_client

    async def deny(_c: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        return False

    monkeypatch.setattr(fga_module, "check", deny)
    resp = client.post(
        "/v1/warehouses", json={"id": "wh-a", "project": "acme"}, headers={"authorization": "Bearer t"}
    )
    assert resp.status_code == 403, resp.text
