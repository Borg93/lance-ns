"""OpenFGA authorization wiring tests (our logic only — fga.check is faked).

Assert our authorize dependency: it derives the right object + relation from the
path, allows on a positive check, and maps a negative check to 403 problem+json.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from lance_namespace import DescribeTableResponse

from app.core import fga as fga_module
from app.core.config import Settings, get_settings
from app.core.oidc import IDToken


def _auth_settings() -> Settings:
    return Settings(
        oidc_enabled=True,
        oidc_issuer="https://idp.example",
        oidc_audience="lance",
        fga_enabled=True,
        fga_api_url="http://openfga:8080",
        s3_access_key_id="x",
        s3_secret_access_key="x",
    )


def _enable(client: TestClient, *, allow: bool, captured: dict) -> object:
    client.app.dependency_overrides[get_settings] = _auth_settings
    verifier = MagicMock()
    verifier.verify.return_value = IDToken(iss="i", sub="alice", aud="lance", exp=1, iat=1)
    client.app.state.oidc = verifier
    fga_client = MagicMock()  # sentinel; fga.check is faked below
    fga_client.close = AsyncMock()  # closed by the lifespan on shutdown
    client.app.state.fga = fga_client

    async def fake_check(_client: object, *, user: str, relation: str, obj: str) -> bool:
        captured.update(user=user, relation=relation, obj=obj)
        return allow

    return fake_check


def test_read_op_checks_reader_and_allows(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    captured: dict = {}
    monkeypatch.setattr(fga_module, "check", _enable(client, allow=True, captured=captured))

    resp = client.post("/v1/table/db1$users/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert captured == {"user": "alice", "relation": "reader", "obj": "table:db1$users"}


def test_write_op_denied_is_403_problem_json(client: TestClient, monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(fga_module, "check", _enable(client, allow=False, captured=captured))

    resp = client.post("/v1/table/db1$users/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert captured["relation"] == "writer"  # a mutation requires writer
    assert captured["obj"] == "table:db1$users"


def test_namespace_op_uses_namespace_object(client: TestClient, monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(fga_module, "check", _enable(client, allow=False, captured=captured))

    resp = client.post("/v1/namespace/db1/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured["obj"] == "namespace:db1"
    assert captured["relation"] == "writer"
