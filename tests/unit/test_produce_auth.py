"""`/produce` must enforce the Dapr app-api-token — an in-cluster caller can't forge the cascade head.

require_dapr_token's own contract is covered in test_dapr_auth; this pins that it is actually WIRED onto the
route (a direct, non-sidecar-delivered POST with no/blank token is rejected once APP_API_TOKEN is set)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from medallion.api.dependencies import get_dapr, get_settings
from medallion.api.produce import router


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_API_TOKEN", "s3cret")
    app = FastAPI()
    app.include_router(router)
    # Fakes so only the token guard is exercised — a rejected request never reaches the handler anyway.
    app.dependency_overrides[get_dapr] = lambda: None
    app.dependency_overrides[get_settings] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def test_produce_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _client(monkeypatch).post("/produce").status_code == 403


def test_produce_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch).post("/produce", headers={"dapr-api-token": "nope"})
    assert response.status_code == 403


def test_produce_token_match_passes_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # Correct token → the guard passes; the handler then runs against the fakes (may 5xx) but is NOT a 403.
    response = _client(monkeypatch).post("/produce", headers={"dapr-api-token": "s3cret"})
    assert response.status_code != 403
