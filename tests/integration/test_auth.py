"""OIDC authentication wiring tests (our logic only — no PyJWT/network).

The verifier is faked, so these assert our dependency's behavior: off → open,
on + no token → 401 problem+json, on + token → delegates to the verifier.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from lance_namespace import ListTablesResponse

from app.core.config import Settings, get_settings
from app.core.oidc import IDToken


def _enabled_settings() -> Settings:
    return Settings(
        oidc_enabled=True,
        oidc_issuer="https://idp.example",
        oidc_audience="lance",
        s3_access_key_id="x",
        s3_secret_access_key="x",
    )


def test_oidc_disabled_leaves_routes_open(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.list_all_tables.return_value = ListTablesResponse(tables=[])
    assert client.get("/v1/table").status_code == 200


def test_oidc_enabled_missing_token_is_401_problem_json(client: TestClient) -> None:
    client.app.dependency_overrides[get_settings] = _enabled_settings
    client.app.state.oidc = MagicMock()  # a verifier is present
    resp = client.get("/v1/table")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == 16  # UNAUTHENTICATED


def test_oidc_enabled_valid_token_passes_through(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.list_all_tables.return_value = ListTablesResponse(tables=[])
    verifier = MagicMock()
    verifier.verify.return_value = IDToken(iss="i", sub="s", aud="lance", exp=1, iat=1)
    client.app.dependency_overrides[get_settings] = _enabled_settings
    client.app.state.oidc = verifier

    resp = client.get("/v1/table", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    verifier.verify.assert_called_once_with("tok")


@pytest.mark.parametrize("missing", ["issuer", "audience"])
def test_settings_rejects_enabled_oidc_without_provider(missing: str) -> None:
    kwargs = {"oidc_issuer": "https://idp.example", "oidc_audience": "lance"}
    kwargs[f"oidc_{missing}"] = None
    with pytest.raises(ValueError, match="OIDC"):
        Settings(oidc_enabled=True, s3_access_key_id="x", s3_secret_access_key="x", **kwargs)
