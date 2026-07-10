"""Ray TRAIN head + trainer consumer (#115a, docs/RAY-TRAIN.md D1/D2/D5) — infra-free unit tier.

Covers the DONE WHEN unit items: the head publishes the pinned trigger (LATEST resolved AT the head),
the token guard is wired on /train, the consumer gates as the trainer identity (deny → DROP, outage →
RETRY), submit-and-ack semantics (bounded, re-attach on redelivery, NO resubmit of a terminally FAILED
prior job), and transport failure → RETRY.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lance_namespace import ServiceUnavailableError
from medallion.api.dependencies import get_dapr, get_settings
from medallion.api.train import router
from medallion.core.config import MedallionSettings
from medallion.services import ray_submit, train


def _settings(**overrides: Any) -> MedallionSettings:
    values: dict[str, Any] = {
        "MEDALLION_RAY_ENABLED": "true",
        "MEDALLION_COMPUTE_ENABLED": "true",
        "MEDALLION_S3_ENDPOINT": "http://rustfs:9000",
        "MEDALLION_S3_SECRET_ACCESS_KEY": "k",
        "MEDALLION_RAW_URI": "s3://lake/medallion/raw",
    }
    values.update(overrides)
    return MedallionSettings.model_validate(values)


class _FakeDapr:
    def __init__(self) -> None:
        self.published: list[dict[str, str]] = []

    async def publish_event(self, *, pubsub_name: str, topic_name: str, data: str, **_kw: Any) -> None:
        self.published.append({"pubsub": pubsub_name, "topic": topic_name, "data": data})


# --------------------------------------------------------------------------- #
# the head: version pinning + trigger publish + route wiring
# --------------------------------------------------------------------------- #


def test_stage_uri_derives_the_sibling_stage_from_the_raw_uri() -> None:
    assert train.stage_uri_for(_settings(), "silver$features") == "s3://lake/medallion/silver"
    assert train.stage_uri_for(_settings(), "gold$catalog") == "s3://lake/medallion/gold"


def test_head_resolves_omitted_versions_at_submit_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # D1: an omitted version pins to LATEST *here* — the trigger never carries a floating version.
    monkeypatch.setattr(train, "_resolve_version", lambda _s, dataset: {"silver$features": 7}[dataset])
    dapr = _FakeDapr()
    result = asyncio.run(
        train.submit_train_request(
            cast(Any, dapr),
            _settings(),
            model="churn",
            features=[{"dataset": "silver$features"}, {"dataset": "gold$catalog", "version": 3}],
        )
    )
    assert result["features"] == [
        {"dataset": "silver$features", "version": 7},  # resolved
        {"dataset": "gold$catalog", "version": 3},  # caller's pin respected verbatim
    ]
    payload = json.loads(dapr.published[0]["data"])
    assert dapr.published[0]["topic"] == "training.jobs"  # the DEDICATED topic (D1)
    assert payload["model"] == "churn" and payload["token"] == result["token"]


def test_head_surfaces_resolution_and_publish_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_s: Any, _d: str) -> int:
        raise RuntimeError("no such dataset")

    monkeypatch.setattr(train, "_resolve_version", boom)
    result = asyncio.run(
        train.submit_train_request(
            cast(Any, _FakeDapr()), _settings(), model="m", features=[{"dataset": "nope$x"}]
        )
    )
    assert result == {"status": "resolve_failed", "dataset": "nope$x"}

    class _BoomDapr:
        async def publish_event(self, **_kw: Any) -> None:
            raise RuntimeError("sidecar down")

    monkeypatch.setattr(train, "_resolve_version", lambda _s, _d: 1)
    result = asyncio.run(
        train.submit_train_request(
            cast(Any, _BoomDapr()), _settings(), model="m", features=[{"dataset": "silver$features"}]
        )
    )
    assert result["status"] == "publish_failed"


def test_train_route_enforces_the_app_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_API_TOKEN", "s3cret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dapr] = lambda: None
    app.dependency_overrides[get_settings] = lambda: _settings()
    client = TestClient(app, raise_server_exceptions=False)
    body = {"model": "m", "features": [{"dataset": "silver$features"}]}
    assert client.post("/train", json=body).status_code == 403
    assert client.post("/train", json=body, headers={"dapr-api-token": "nope"}).status_code == 403


def test_train_route_409_when_the_head_is_not_configured() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dapr] = lambda: None
    app.dependency_overrides[get_settings] = lambda: _settings(MEDALLION_RAY_ENABLED="false")
    response = TestClient(app).post("/train", json={"model": "m", "features": [{"dataset": "a$b"}]})
    assert response.status_code == 409  # explicit contract, never a silent 202


# --------------------------------------------------------------------------- #
# the consumer: FGA gates (D5) + submit-and-ack (D2)
# --------------------------------------------------------------------------- #

_EVENT = {
    "data": {
        "token": "t1",
        "model": "churn",
        "features": [{"dataset": "silver$features", "version": 7}],
    }
}


def _gate(allowed: dict[str, bool]) -> Any:
    async def check(_client: Any, *, user: str, relation: str, obj: str) -> bool:
        assert user == "service-trainer"  # the trainer's OWN identity, never the mover rung (D5)
        return allowed[f"{relation}:{obj}"]

    return check


def test_consumer_denied_input_or_models_rung_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(
        train.ray_submit,
        "submit_train_job",
        lambda *a, **k: submitted.append("x"),  # never awaited
    )
    monkeypatch.setattr(
        train.fga,
        "check",
        _gate({"can_read_data:table:silver$features": False}),
    )
    result = asyncio.run(train.handle_train_trigger(_settings(), _EVENT, fga_client=object()))
    assert result == {"status": "DROP"} and submitted == []  # denied BEFORE any compute is spent

    monkeypatch.setattr(
        train.fga,
        "check",
        _gate({"can_read_data:table:silver$features": True, "can_create_table:namespace:models": False}),
    )
    result = asyncio.run(train.handle_train_trigger(_settings(), _EVENT, fga_client=object()))
    assert result == {"status": "DROP"} and submitted == []


def test_consumer_fga_outage_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def outage(*_a: Any, **_kw: Any) -> bool:
        raise ServiceUnavailableError("fga down")

    monkeypatch.setattr(train.fga, "check", outage)
    result = asyncio.run(train.handle_train_trigger(_settings(), _EVENT, fga_client=object()))
    assert result == {"status": "RETRY"}  # outage ≠ denial


def test_consumer_submits_and_acks_and_maps_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = iter(["submitted", "attached", "already_failed"])
    calls: list[str] = []

    async def fake_submit(_s: Any, *, model: str, features_json: str, token: str, **_kw: Any) -> str:
        calls.append(token)
        assert json.loads(features_json) == [{"dataset": "silver$features", "version": 7}]
        return next(outcomes)

    monkeypatch.setattr(train.ray_submit, "submit_train_job", fake_submit)
    assert asyncio.run(train.handle_train_trigger(_settings(), _EVENT)) == {"status": "SUCCESS"}
    assert asyncio.run(train.handle_train_trigger(_settings(), _EVENT)) == {"status": "SUCCESS"}  # re-attach
    # a terminally FAILED prior job is DROPPED — training is never auto-resubmitted (D2)
    assert asyncio.run(train.handle_train_trigger(_settings(), _EVENT)) == {"status": "DROP"}
    assert calls == ["t1", "t1", "t1"]

    async def transport_error(*_a: Any, **_kw: Any) -> str:
        raise ray_submit.RayJobError("submit failed")

    monkeypatch.setattr(train.ray_submit, "submit_train_job", transport_error)
    assert asyncio.run(train.handle_train_trigger(_settings(), _EVENT)) == {"status": "RETRY"}

    assert asyncio.run(train.handle_train_trigger(_settings(), {"data": {}})) == {"status": "DROP"}


def test_consumer_drops_unpinned_or_empty_features(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review 2026-07-10: a version-less feature would train on floating LATEST (violates D1) and an
    # empty-after-filter list would gate vacuously — both are malformed triggers: DROP, never repair.
    async def never(*_a: Any, **_kw: Any) -> str:
        raise AssertionError("must not submit")

    monkeypatch.setattr(train.ray_submit, "submit_train_job", never)
    unpinned = {"data": {"token": "t", "model": "m", "features": [{"dataset": "silver$features"}]}}
    assert asyncio.run(train.handle_train_trigger(_settings(), unpinned)) == {"status": "DROP"}
    junk = {"data": {"token": "t", "model": "m", "features": ["junk"]}}
    assert asyncio.run(train.handle_train_trigger(_settings(), junk)) == {"status": "DROP"}
    empty = {"data": {"token": "t", "model": "m", "features": []}}
    assert asyncio.run(train.handle_train_trigger(_settings(), empty)) == {"status": "DROP"}


def test_head_rejects_an_oversized_config() -> None:
    # Claim-check: the trigger carries pointers + hyperparams, never data-shaped content.
    result = asyncio.run(
        train.submit_train_request(
            cast(Any, _FakeDapr()),
            _settings(),
            model="m",
            features=[{"dataset": "a$b", "version": 1}],
            config={"blob": "x" * 10_000},
        )
    )
    assert result == {"status": "config_too_large"}


# --------------------------------------------------------------------------- #
# submit_train_job against a fake Ray Jobs API — the D2 semantics at the transport
# --------------------------------------------------------------------------- #


class _FakeJobsAPI:
    """Programmable stand-in for httpx.AsyncClient against the Ray Jobs REST API."""

    def __init__(self, post_status: int, existing_status: str | None) -> None:
        self.posts: list[dict[str, Any]] = []
        self.deletes: list[str] = []
        self._post_status = post_status
        self._existing = existing_status

    async def __aenter__(self) -> _FakeJobsAPI:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def post(self, _url: str, json: dict[str, Any]) -> Any:
        self.posts.append(json)
        return httpx.Response(self._post_status, request=httpx.Request("POST", "http://ray"))

    async def get(self, url: str) -> Any:
        assert self._existing is not None, f"unexpected GET {url}"
        return httpx.Response(
            200, request=httpx.Request("GET", "http://ray"), json={"status": self._existing}
        )

    async def delete(self, url: str) -> Any:  # pragma: no cover — MUST never be called for train
        raise AssertionError(f"train path must never DELETE a prior job (got {url})")


def _run_submit(monkeypatch: pytest.MonkeyPatch, api: _FakeJobsAPI) -> str:
    def make_client(**kw: Any) -> _FakeJobsAPI:
        # The ack-window bound: EVERY await inside submit_train_job runs under this client timeout —
        # a refactor dropping it would un-bound the handler against a hung Ray API (review 2026-07-10).
        assert kw["timeout"] == _settings().ray_request_timeout_seconds
        return api

    monkeypatch.setattr(ray_submit.httpx, "AsyncClient", make_client)
    return asyncio.run(
        ray_submit.submit_train_job(_settings(), model="churn", features_json="[]", token="tok1")
    )


def test_submit_train_job_fresh_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _FakeJobsAPI(post_status=200, existing_status=None)
    assert _run_submit(monkeypatch, api) == "submitted"
    assert api.posts[0]["submission_id"] == "ray-train-tok1"  # deterministic idempotency key
    assert api.posts[0]["entrypoint"].endswith("ray_train_job.py")


def test_submit_train_job_reattaches_to_a_running_job(monkeypatch: pytest.MonkeyPatch) -> None:
    # Redelivery: the POST 4xxs (id exists), the job is RUNNING → attach, no second job, no delete.
    api = _FakeJobsAPI(post_status=409, existing_status="RUNNING")
    assert _run_submit(monkeypatch, api) == "attached"
    assert len(api.posts) == 1  # exactly one submit attempt — never a duplicate job


def test_submit_train_job_never_resubmits_a_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    # D2: unlike the stage path (delete + fresh resubmit), a FAILED training job is terminal.
    api = _FakeJobsAPI(post_status=409, existing_status="FAILED")
    assert _run_submit(monkeypatch, api) == "already_failed"
    assert len(api.posts) == 1 and api.deletes == []
