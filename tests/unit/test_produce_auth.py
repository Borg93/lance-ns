"""Fail-closed dual-auth for the /produce + /train triggers (#64): service token OR project-admin OIDC.

The cascade head is provenance-fabricatable, so the ADMIN door added for the UI must not be bypassable:
an invalid bearer 401s, a non-admin 403s, an FGA outage 503s (never a silent allow), and a request carrying
no credential 403s. The service-token path is UNCHANGED, and dev (no APP_API_TOKEN) stays open.

Two layers: direct-function tests pin every fail-closed branch of :func:`authorize_produce` (sync via
``asyncio.run`` — no async-plugin dependency); the TestClient tests pin that it is actually WIRED onto the
``/produce`` route (a direct, non-sidecar POST is gated end-to-end), which the function tests can't prove.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from lance_namespace import ServiceUnavailableError, UnauthenticatedError
from medallion.api import produce_auth
from medallion.api.dependencies import get_dapr, get_settings
from medallion.api.produce import router
from medallion.core.config import MedallionSettings
from openfga_sdk import OpenFgaClient

# ── direct-function tests: every fail-closed branch of authorize_produce ──────────────────────────


class _Verifier:
    def __init__(self, sub: str = "alice", *, invalid: bool = False) -> None:
        self._sub, self._invalid = sub, invalid

    def verify(self, _token: str) -> object:  # the fake ignores the token
        if self._invalid:
            raise UnauthenticatedError("bad token")
        return SimpleNamespace(sub=self._sub)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_token: str | None,
    dapr_token: str | None = None,
    authz: str | None = None,
    verifier: object | None = None,
    oidc_enabled: bool = True,
    fga_result: bool = True,
    fga_raises: bool = False,
    project: str | None = None,
    captured: dict[str, object] | None = None,
) -> None:
    if app_token is None:
        monkeypatch.delenv("APP_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("APP_API_TOKEN", app_token)

    async def fake_check(_client: object, **kw: object) -> bool:  # user=/relation=/obj= arrive as kwargs
        if captured is not None:
            captured.update(kw)
        if fga_raises:
            raise ServiceUnavailableError("fga down")
        return fga_result

    monkeypatch.setattr(produce_auth.fga, "check", fake_check)
    ns = SimpleNamespace(oidc_enabled=oidc_enabled, produce_admin_project="acme")
    request = cast(Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(oidc=verifier))))
    settings = cast(MedallionSettings, ns)
    return asyncio.run(
        produce_auth.authorize_produce(
            request,
            settings,
            cast(OpenFgaClient, object()),
            dapr_api_token=dapr_token,
            authorization=authz,
            project=project,
        )
    )


def _expect(monkeypatch: pytest.MonkeyPatch, status: int, **kw: object) -> None:
    with pytest.raises(HTTPException) as exc:
        _run(monkeypatch, **kw)  # ty: ignore[invalid-argument-type]
    assert exc.value.status_code == status


def test_dev_open_when_no_service_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, app_token=None) is None  # dev no-op, exactly like require_dapr_token


def test_service_token_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, app_token="s3cr3t", dapr_token="s3cr3t") is None


def test_oidc_admin_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        _run(monkeypatch, app_token="s3cr3t", authz="Bearer good", verifier=_Verifier(), fga_result=True)
        is None
    )


def test_oidc_nonadmin_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 403, app_token="s3cr3t", authz="Bearer good", verifier=_Verifier(), fga_result=False)


def test_invalid_bearer_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 401, app_token="s3cr3t", authz="Bearer bad", verifier=_Verifier(invalid=True))


def test_malformed_authorization_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 401, app_token="s3cr3t", authz="Basic xyz", verifier=_Verifier())


def test_fga_outage_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 503, app_token="s3cr3t", authz="Bearer good", verifier=_Verifier(), fga_raises=True)


def test_no_credential_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 403, app_token="s3cr3t")  # token set, no dapr token, no bearer, no verifier


def test_bearer_but_oidc_disabled_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bearer is presented but OIDC is off → the human door is shut; never a silent allow.
    _expect(
        monkeypatch, 403, app_token="s3cr3t", authz="Bearer good", verifier=_Verifier(), oidc_enabled=False
    )


def test_wrong_service_token_and_oidc_off_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(monkeypatch, 403, app_token="s3cr3t", dapr_token="wrong", oidc_enabled=False)


# ── route-wiring tests: authorize_produce is actually mounted on POST /produce ────────────────────


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_API_TOKEN", "s3cret")
    app = FastAPI()
    app.include_router(router)
    # Fakes so only the guard is exercised — a rejected request never reaches the handler anyway. Settings
    # carries oidc_enabled=False (no verifier wired on app.state) so the human door stays shut in the test.
    app.dependency_overrides[get_dapr] = lambda: None
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        oidc_enabled=False, produce_admin_project="acme"
    )
    return TestClient(app, raise_server_exceptions=False)


def test_route_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _client(monkeypatch).post("/produce").status_code == 403


def test_route_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _client(monkeypatch).post("/produce", headers={"dapr-api-token": "nope"}).status_code == 403


def test_route_token_match_passes_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # Correct token → the guard passes; the handler then runs against the fakes (may 5xx) but is NOT a 403.
    response = _client(monkeypatch).post("/produce", headers={"dapr-api-token": "s3cret"})
    assert response.status_code != 403


# ── GET /authorize (#77 audit admin gate): the SAME door, side-effect-free ─────────────────────────


def test_authorize_route_rejects_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    # The web audit BFF relies on this: a non-admin (no credential) must be refused, never 200.
    assert _client(monkeypatch).get("/authorize").status_code == 403


def test_authorize_route_allows_the_admin_door(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _client(monkeypatch).get("/authorize", headers={"dapr-api-token": "s3cret"})
    assert res.status_code == 200 and res.json() == {"authorized": True}


# ── #84 per-tenant produce: the admin gate follows the REQUESTED project ───────────────────────────


def test_oidc_admin_gate_targets_the_requested_project(monkeypatch: pytest.MonkeyPatch) -> None:
    # A caller producing into project X must administer X — not the fixed configured project.
    captured: dict[str, object] = {}
    _run(
        monkeypatch,
        app_token="s3cr3t",
        authz="Bearer good",
        verifier=_Verifier(),
        project="globex",
        captured=captured,
    )
    assert captured["obj"] == "project:globex"


def test_oidc_admin_gate_defaults_to_the_configured_project(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    _run(monkeypatch, app_token="s3cr3t", authz="Bearer good", verifier=_Verifier(), captured=captured)
    assert captured["obj"] == "project:acme"  # no project param → exactly the pre-#84 gate


def test_service_token_with_the_configured_project_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    # The service path stays open for the project it is configured to produce into.
    assert _run(monkeypatch, app_token="s3cr3t", dapr_token="s3cr3t", project="acme") is None


def test_service_token_cannot_request_another_project(monkeypatch: pytest.MonkeyPatch) -> None:
    # The shared app token authenticates the SERVICE, not a tenant — trusting it for an arbitrary
    # requested project would let any token holder produce into every tenant. Cross-project requests
    # take a user bearer — the per-project FGA check test_oidc_admin_gate_targets_the_requested_project pins.
    _expect(monkeypatch, 403, app_token="s3cr3t", dapr_token="s3cr3t", project="globex")


def test_nonadmin_of_the_requested_project_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect(
        monkeypatch,
        403,
        app_token="s3cr3t",
        authz="Bearer good",
        verifier=_Verifier(),
        fga_result=False,
        project="globex",
    )


def test_route_rejects_a_malformed_project_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # The project becomes an S3 prefix + lineage qualifier — a path-shaped value is refused at the edge.
    res = _client(monkeypatch).get(
        "/authorize", params={"project": "../evil"}, headers={"dapr-api-token": "s3cret"}
    )
    assert res.status_code == 422


def test_produce_route_409s_when_project_routing_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Dev-open door + real settings (control_root unset): a project-carrying produce is REFUSED (409,
    # problem+json), never silently seeded into the shared root.
    monkeypatch.delenv("APP_API_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dapr] = lambda: None
    app.dependency_overrides[get_settings] = lambda: MedallionSettings.model_validate({})
    res = TestClient(app, raise_server_exceptions=False).post("/produce", params={"project": "acme"})
    assert res.status_code == 409
    assert res.headers["content-type"].startswith("application/problem+json")
