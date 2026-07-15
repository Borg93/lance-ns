"""Integration tests for the #17 model-promotion endpoints — governance + flow through the REAL catalog app.

Mirrors ``test_authz``'s harness: OIDC+FGA enabled via a ``get_settings`` override, a faked verifier (user
``alice``) + a sentinel FGA client, and ``fga.check`` monkeypatched to allow/deny. The registry is a REAL
Lance dataset written under ``<root>/medallion/models/<model>`` (a local ``dir`` root), so the endpoint's
URI-direct open, metrics gate, and blessed-tag move are exercised end to end. The rung SEPARATION against a
real OpenFGA (validator promotes, writer denied) is proven additionally by the live e2e.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import lance
import pyarrow as pa
import pytest
from catalog.api.dependencies import get_settings
from catalog.core.config import Settings
from common import fga as fga_module
from common.oidc import IDToken
from fastapi.testclient import TestClient


def _publish(uri: str, metrics: dict[str, Any], token: str, *, first: bool) -> int:
    meta = {"config": {}, "features": ["silver$features"], "metrics": metrics, "token": token}
    table = pa.table(
        {
            "artifact": pa.array(["weights", "config"], pa.string()),
            "meta": pa.array([json.dumps(meta)] * 2, pa.string()),
        }
    )
    if first:
        ds = lance.write_dataset(
            table, uri, mode="overwrite", data_storage_version="2.2", enable_stable_row_ids=True
        )
    else:
        ds = lance.write_dataset(table, uri, mode="append")
    return int(ds.version)


@pytest.fixture
def models_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, str]]:
    root = str(tmp_path)
    # The lifespan builds the namespace from ENV (FGA/OIDC OFF so startup needs no real IdP); request handling
    # uses the override below (FGA/OIDC ON) + injected mocks — exactly test_authz's split.
    monkeypatch.setenv("LANCE_REST_IMPL", "dir")
    monkeypatch.setenv("LANCE_REST_ROOT", root)
    monkeypatch.setenv("LANCE_S3_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("LANCE_S3_SECRET_ACCESS_KEY", "x")
    get_settings.cache_clear()  # the lifespan reads env-based settings; rebuild with ours (test-order-safe)

    def _settings() -> Settings:
        return Settings.model_validate(
            {
                "impl": "dir",
                "root": root,
                "oidc_enabled": True,
                "oidc_issuer": "https://idp.example",
                "oidc_audience": "lance",
                "fga_enabled": True,
                "fga_api_url": "http://openfga:8080",
                "s3_access_key_id": "x",
                "s3_secret_access_key": "x",
            }
        )

    registry = f"{root}/medallion/models/demo"
    _publish(registry, {"rows_seen": 4, "features": 1}, "tok-v1", first=True)
    _publish(registry, {"rows_seen": 9, "features": 1}, "tok-v2", first=False)

    # Imported HERE (not at module top) so the app's module-level ``get_settings()`` runs AFTER the env
    # above is set — the same reason the conftest fixtures import the app lazily (test-order-safe).
    from catalog.main import app

    with TestClient(app) as client:
        client.app.dependency_overrides[get_settings] = _settings
        verifier = MagicMock()
        verifier.verify.return_value = IDToken(iss="i", sub="alice", aud="lance", exp=1, iat=1)
        client.app.state.oidc = verifier
        fga_client = MagicMock()
        fga_client.close = AsyncMock()
        client.app.state.fga = fga_client
        yield client, registry
        client.app.dependency_overrides.clear()
    get_settings.cache_clear()


def _fake_check(captured: list[dict], *, allow: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_c: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        captured.append({"user": user, "relation": relation, "obj": obj})
        return allow

    monkeypatch.setattr(fga_module, "check", fake)


def test_promote_checks_can_promote_and_moves_blessed_tag(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONTRACT: promote gates on the VALIDATOR rung (can_promote on table:models$demo) and moves the tag.
    client, registry = models_client
    captured: list[dict] = []
    _fake_check(captured, allow=True, monkeypatch=monkeypatch)

    resp = client.post("/v1/model/demo/promote", headers={"Authorization": "Bearer t"}, json={"version": 2})

    assert resp.status_code == 200, resp.text
    assert resp.json()["blessed_version"] == 2
    assert {"user": "alice", "relation": "can_promote", "obj": "table:models$demo"} in captured
    assert lance.dataset(registry).tags.get_version("blessed") == 2  # the tag really moved


def test_promote_denied_to_a_non_validator(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A plain writer (or the trainer) is NOT a validator → 403, and the tag is never created.
    client, registry = models_client
    _fake_check([], allow=False, monkeypatch=monkeypatch)

    resp = client.post("/v1/model/demo/promote", headers={"Authorization": "Bearer t"}, json={"version": 2})

    assert resp.status_code == 403
    with pytest.raises(ValueError, match="not found|Ref"):  # tag never created on a denied promote
        lance.dataset(registry).tags.get_version("blessed")


def test_promote_fails_closed_when_fga_client_is_missing(
    models_client: tuple[TestClient, str],
) -> None:
    # FGA enabled but no client wired → 503, never an open promote.
    client, _ = models_client
    client.app.state.fga = None

    resp = client.post("/v1/model/demo/promote", headers={"Authorization": "Bearer t"}, json={"version": 2})

    assert resp.status_code == 503


def test_promote_requires_authentication(models_client: tuple[TestClient, str]) -> None:
    client, _ = models_client  # OIDC on, no bearer → 401 before any FGA/registry work
    resp = client.post("/v1/model/demo/promote", json={"version": 2})
    assert resp.status_code == 401


def test_metrics_gate_blocks_a_low_version(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Authorized, but v1 (rows_seen=4) misses the rows_seen>=8 bar → 409, tag untouched.
    client, registry = models_client
    _fake_check([], allow=True, monkeypatch=monkeypatch)

    resp = client.post(
        "/v1/model/demo/promote",
        headers={"Authorization": "Bearer t"},
        json={"version": 1, "min_metrics": {"rows_seen": 8}},
    )

    assert resp.status_code == 409, resp.text
    with pytest.raises(ValueError, match="not found|Ref"):
        lance.dataset(registry).tags.get_version("blessed")


def test_describe_checks_reader_and_reports_candidate_plus_blessed(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = models_client
    captured: list[dict] = []
    _fake_check(captured, allow=True, monkeypatch=monkeypatch)

    resp = client.get("/v1/model/demo", headers={"Authorization": "Bearer t"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["latest_version"] == 2
    assert body["candidate_metrics"] == {"rows_seen": 9, "features": 1}
    assert {"user": "alice", "relation": "can_get_metadata", "obj": "table:models$demo"} in captured


def test_promote_unknown_model_is_404(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = models_client
    _fake_check([], allow=True, monkeypatch=monkeypatch)
    resp = client.post("/v1/model/ghost/promote", headers={"Authorization": "Bearer t"}, json={"version": 1})
    assert resp.status_code == 404


def test_promote_rejects_an_arbitrary_tag(
    models_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is "promote" (a known lifecycle tag), not "create any tag" — a caller-named ref is a 400.
    client, registry = models_client
    _fake_check([], allow=True, monkeypatch=monkeypatch)
    resp = client.post(
        "/v1/model/demo/promote",
        headers={"Authorization": "Bearer t"},
        json={"version": 2, "tag": "pwned"},
    )
    assert resp.status_code == 400
    with pytest.raises(ValueError, match="not found|Ref"):
        lance.dataset(registry).tags.get_version("pwned")  # the arbitrary tag was never created
