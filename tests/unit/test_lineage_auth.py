"""Unit tests for the lineage service's auth gate (audit ``w8u4rc2tg``, P0 #1/#2).

Infra-free, like ``test_lineage.py``: no database, no network. Drives the async gate with
stdlib ``asyncio.run`` (the project convention — see ``test_fga_resilience.py``) and fakes
the OpenFGA check + the OIDC verifier.

Covers:
* fail-closed config (a half-configured auth layer is a startup error),
* authn (off → open; on → token required / verified / fail-closed when unwired),
* the read authz gate (off → allow; unwired → 503; unauthenticated → 401; deny → 403; allow),
* author-forgery prevention (the verified subject overrides any body-claimed author),
* route wiring (the gate is actually attached to the endpoints).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
from lance_namespace import PermissionDeniedError, ServiceUnavailableError, UnauthenticatedError
from openfga_sdk import OpenFgaClient
from pydantic import ValidationError

from app.core import fga
from app.core.oidc import IDToken
from lineage import auth
from lineage.config import LineageSettings
from lineage.models import RunEvent
from lineage.repository import LineageRepository
from lineage.schemas import DatasetRef, Neighbors

_ISSUER = "https://idp.example.com"


def _settings(**values: Any) -> LineageSettings:
    """Build settings from field names (``model_validate`` runs the fail-closed validator)."""
    return LineageSettings.model_validate(values)


def _token(sub: str = "alice") -> IDToken:
    return IDToken(iss=_ISSUER, sub=sub, aud="lance", exp=0, iat=0)


def _request(**state: object) -> Request:
    """A fake request exposing only ``request.app.state`` (the gate reads ``oidc``/``fga``)."""
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state))))


def _creds(value: str = "tok") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=value)


_FULL_AUTH = {
    "oidc_enabled": True,
    "oidc_issuer": _ISSUER,
    "oidc_audience": "lance",
    "fga_enabled": True,
    "fga_store_id": "store",
    "fga_model_id": "model",
}


# --------------------------------------------------------------------------- #
# Fail-closed config
# --------------------------------------------------------------------------- #


def test_oidc_enabled_requires_issuer_and_audience() -> None:
    with pytest.raises(ValidationError):
        _settings(oidc_enabled=True)


def test_fga_enabled_requires_oidc() -> None:
    with pytest.raises(ValidationError):
        _settings(fga_enabled=True, oidc_enabled=False)


def test_fga_enabled_requires_store_and_model() -> None:
    with pytest.raises(ValidationError):
        _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance", fga_enabled=True)


def test_full_auth_config_is_valid() -> None:
    assert _settings(**_FULL_AUTH).fga_object_type == "table"


# --------------------------------------------------------------------------- #
# authenticate (authn)
# --------------------------------------------------------------------------- #


def test_authenticate_disabled_returns_none() -> None:
    assert auth.authenticate(_request(), _settings(), None) is None


def test_authenticate_enabled_missing_token_raises() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    verifier = SimpleNamespace(verify=lambda _t: _token())
    with pytest.raises(UnauthenticatedError):
        auth.authenticate(_request(oidc=verifier), settings, None)


def test_authenticate_enabled_unwired_verifier_fails_closed() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    with pytest.raises(ServiceUnavailableError):
        auth.authenticate(_request(), settings, _creds())


def test_authenticate_enabled_verifies_token() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    verifier = SimpleNamespace(verify=lambda _t: _token("dee"))
    token = auth.authenticate(_request(oidc=verifier), settings, _creds())
    assert token is not None and token.sub == "dee"


# --------------------------------------------------------------------------- #
# require_metadata_access (read authz gate)
# --------------------------------------------------------------------------- #


def test_gate_disabled_allows() -> None:
    # FGA off → no check, no raise (dev/test default, like the catalog).
    asyncio.run(auth.require_metadata_access("a$b", _request(), _settings(), None))


def test_gate_unwired_client_fails_closed() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(auth.require_metadata_access("a$b", _request(), _settings(**_FULL_AUTH), _token()))


def test_gate_unauthenticated_raises() -> None:
    with pytest.raises(UnauthenticatedError):
        asyncio.run(
            auth.require_metadata_access("a$b", _request(fga=object()), _settings(**_FULL_AUTH), None)
        )


def test_gate_denies_without_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _deny(_client: object, *, user: str, relation: str, obj: str) -> bool:
        captured.update(user=user, relation=relation, obj=obj)
        return False

    monkeypatch.setattr(fga, "check", _deny)
    client = cast(OpenFgaClient, object())
    with pytest.raises(PermissionDeniedError):
        asyncio.run(
            auth.require_metadata_access("a$b", _request(fga=client), _settings(**_FULL_AUTH), _token())
        )
    # The denial must be on the right user/object/relation, not just "some" denial.
    assert captured == {"user": "alice", "relation": "can_get_metadata", "obj": "table:a$b"}


def test_gate_allows_with_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _allow(_client: object, *, user: str, relation: str, obj: str) -> bool:
        captured.update(user=user, relation=relation, obj=obj)
        return True

    monkeypatch.setattr(fga, "check", _allow)
    client = cast(OpenFgaClient, object())
    asyncio.run(
        auth.require_metadata_access("a$b", _request(fga=client), _settings(**_FULL_AUTH), _token("dee"))
    )
    # The dataset name is gated as table:<name> with the catalog's metadata-read relation.
    assert captured == {"user": "dee", "relation": "can_get_metadata", "obj": "table:a$b"}


# --------------------------------------------------------------------------- #
# enforce_author (provenance forgery prevention)
# --------------------------------------------------------------------------- #


def _event(claimed_author: str) -> RunEvent:
    return RunEvent.model_validate(
        {
            "eventType": "COMPLETE",
            "eventTime": "2026-06-24T00:00:00Z",
            "run": {"runId": "r1", "facets": {"author": {"name": claimed_author}}},
            "job": {"namespace": "jobs", "name": "promote"},
        }
    )


def test_enforce_author_overrides_body_claim() -> None:
    event = _event(claimed_author="attacker")
    auth.enforce_author(event, _token("real-user"))
    assert event.author == "real-user"  # body claim is overwritten by the verified subject


def test_enforce_author_keeps_body_when_unauthenticated() -> None:
    event = _event(claimed_author="claimed")
    auth.enforce_author(event, None)  # OIDC off (dev) → body author preserved
    assert event.author == "claimed"


# --------------------------------------------------------------------------- #
# Route wiring — the gate is actually attached to the endpoints
# --------------------------------------------------------------------------- #


def test_read_routes_wire_the_metadata_gate() -> None:
    from lineage.main import app

    gated = {
        "/datasets/{name}/upstream",
        "/datasets/{name}/downstream",
        "/datasets/{name}/producers",
        "/datasets/{name}/graph",
        "/datasets/{name}/creator",
    }
    seen = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in gated:
            calls = [d.call for d in route.dependant.dependencies]
            assert auth.require_metadata_access in calls, route.path
            seen.add(route.path)
    assert seen == gated  # all four reads are present and gated


def test_ingest_route_requires_authentication() -> None:
    from lineage.main import app

    ingest = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/v1/lineage")
    calls = [d.call for d in ingest.dependant.dependencies]
    assert auth.authenticate in calls


# --------------------------------------------------------------------------- #
# DatasetFilter — transitive-disclosure filtering (audit w8u4rc2tg, security medium)
# --------------------------------------------------------------------------- #


def test_filter_passthrough_when_fga_off() -> None:
    flt = auth.DatasetFilter(_request(), _settings(), None)
    assert asyncio.run(flt.visible(["a", "b"])) == {"a", "b"}


def test_filter_empty_names_skips_check() -> None:
    flt = auth.DatasetFilter(_request(fga=object()), _settings(**_FULL_AUTH), _token())
    assert asyncio.run(flt.visible([])) == set()


async def _batch_allow_a(_client: object, *, objects: list[str], **_kw: object) -> dict[str, bool]:
    """Fake batch_check: only ``table:a`` is visible."""
    return {o: o == "table:a" for o in objects}


def test_filter_drops_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), _settings(**_FULL_AUTH), _token())
    assert asyncio.run(flt.visible(["a", "b"])) == {"a"}


# --------------------------------------------------------------------------- #
# Handler-body behavior the route-dependency introspection can't see:
# the read handler must APPLY the filter, and ingest must bind the verified author.
# --------------------------------------------------------------------------- #


class _FakeRepo:
    """Minimal repository: captures the ingested event / returns two canned neighbors."""

    def __init__(self) -> None:
        self.ingested: RunEvent | None = None

    async def ingest_event(self, event: RunEvent) -> None:
        self.ingested = event

    async def upstream(self, name: str) -> Neighbors:
        return Neighbors(dataset=name, related=[DatasetRef(name="a"), DatasetRef(name="b")])


def test_get_upstream_drops_unauthorized_related(monkeypatch: pytest.MonkeyPatch) -> None:
    from lineage.main import get_upstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), _settings(**_FULL_AUTH), _token())
    result = asyncio.run(get_upstream("root", cast(LineageRepository, _FakeRepo()), flt))
    assert [ref.name for ref in result.related] == ["a"]  # "b" is filtered out


def test_ingest_handler_binds_verified_author() -> None:
    from lineage.main import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="attacker")
    req = _request(events=[], event_seq=0)
    asyncio.run(ingest_event(event, cast(LineageRepository, repo), _token("real-user"), req))
    assert repo.ingested is not None and repo.ingested.author == "real-user"  # body claim overridden


def test_ingest_handler_keeps_body_author_when_oidc_off() -> None:
    from lineage.main import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="claimed")
    req = _request(events=[], event_seq=0)
    asyncio.run(ingest_event(event, cast(LineageRepository, repo), None, req))
    assert repo.ingested is not None and repo.ingested.author == "claimed"
