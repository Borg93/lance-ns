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
from common import fga
from common.oidc import IDToken
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
from lance_namespace import PermissionDeniedError, ServiceUnavailableError, UnauthenticatedError
from lineage import auth
from lineage.config import LineageSettings
from lineage.models import RunEvent
from lineage.repository import LineageRepository
from lineage.schemas import (
    ColumnEdge,
    ColumnGraph,
    ColumnNeighbors,
    ColumnNode,
    ColumnRef,
    DatasetRef,
    DatasetSchema,
    EventRecord,
    Neighbors,
    Runs,
    RunStatus,
    SchemaField,
)
from openfga_sdk import OpenFgaClient
from pydantic import ValidationError

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
        "/datasets/{name}/reconcile",
        "/datasets/{name}/schema",
        "/datasets/{name}/columns/{field}/upstream",
        "/datasets/{name}/columns/{field}/downstream",
        "/datasets/{name}/columns",
    }
    seen = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in gated:
            calls = [d.call for d in route.dependant.dependencies]
            assert auth.require_metadata_access in calls, route.path
            seen.add(route.path)
    assert seen == gated  # every per-dataset read is present and gated


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
        self.events: list[EventRecord] = []
        self.runs: list[RunStatus] = []
        self.write_version: int | None = None
        self.uri: str | None = None
        self.col_related: list[ColumnRef] = []
        self.col_graph: ColumnGraph | None = None

    async def ingest_event(self, event: RunEvent) -> None:
        self.ingested = event

    async def record_event(self, **_kwargs: object) -> None:
        return None

    async def list_events(self, limit: int = 500) -> list[EventRecord]:  # noqa: ARG002
        return self.events

    async def list_runs(self) -> Runs:
        return Runs(runs=self.runs)

    async def latest_write_version(self, name: str) -> int | None:  # noqa: ARG002
        return self.write_version

    async def source_uri(self, name: str) -> str | None:  # noqa: ARG002
        return self.uri

    async def dataset_schema(self, name: str, version: int | None = None) -> DatasetSchema:
        return DatasetSchema(dataset=name, version=version or 2, fields=[SchemaField(name="id", type="int")])

    async def column_upstream(self, dataset: str, field: str) -> ColumnNeighbors:
        return ColumnNeighbors(dataset=dataset, field=field, related=self.col_related)

    async def column_downstream(self, dataset: str, field: str) -> ColumnNeighbors:
        return ColumnNeighbors(dataset=dataset, field=field, related=self.col_related)

    async def dataset_column_graph(self, name: str) -> ColumnGraph:
        return self.col_graph or ColumnGraph(root=name)

    async def upstream(self, name: str) -> Neighbors:
        return Neighbors(dataset=name, related=[DatasetRef(name="a"), DatasetRef(name="b")])


def test_get_upstream_drops_unauthorized_related(monkeypatch: pytest.MonkeyPatch) -> None:
    from lineage.main import get_upstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), _settings(**_FULL_AUTH), _token())
    result = asyncio.run(get_upstream("root", cast(LineageRepository, _FakeRepo()), flt))
    assert [ref.name for ref in result.related] == ["a"]  # "b" is filtered out


def test_get_events_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22: the durable events feed is governed — drop events referencing a dataset the caller can't see.
    from lineage.main import get_events

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.events = [
        EventRecord(seq=2, outputs=["a"], inputs=[], event={}),
        EventRecord(seq=1, outputs=["b"], inputs=[], event={}),  # "b" not visible → dropped
    ]
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_events(cast(LineageRepository, repo), flt, settings))
    assert [e.outputs for e in result.events] == [["a"]]  # the "b" event is filtered out


def test_get_events_hides_dataset_less_events_when_governed(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22 audit: a dataset-less event (empty inputs+outputs) must NOT pass the gate vacuously when FGA is
    # on — it would otherwise leak the run/author/full event JSON to a caller with zero grants.
    from lineage.main import get_events

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.events = [EventRecord(seq=1, outputs=[], inputs=[], event={"run": {"runId": "secret"}})]
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_events(cast(LineageRepository, repo), flt, settings))
    assert result.events == []  # dataset-less event is hidden under governance


def test_get_column_upstream_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #24: column provenance is governed — a related column in a dataset the caller can't see is dropped
    # (a column has no ACL of its own; it inherits its owning table's visibility).
    from lineage.main import get_column_upstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.col_related = [ColumnRef(dataset="a", field="x"), ColumnRef(dataset="b", field="y")]
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_column_upstream("a", "root", cast(LineageRepository, repo), flt, settings))
    assert [(r.dataset, r.field) for r in result.related] == [("a", "x")]  # b's column is hidden


def test_get_column_downstream_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #24: column IMPACT is governed identically to provenance — a related column in a hidden dataset drops.
    from lineage.main import get_column_downstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.col_related = [ColumnRef(dataset="a", field="x"), ColumnRef(dataset="b", field="y")]
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_column_downstream("a", "root", cast(LineageRepository, repo), flt, settings))
    assert [(r.dataset, r.field) for r in result.related] == [("a", "x")]  # b's column is hidden


def test_get_dataset_columns_drops_edges_touching_hidden_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #24: the column-graph view drops nodes/edges touching a dataset the caller can't see. An edge needs
    # BOTH endpoints visible — a 3-edge fixture proves selectivity in BOTH leak directions (source-hidden
    # AND target-hidden), not just one — same transitive-disclosure guarantee as /graph, at column res.
    from lineage.main import get_dataset_columns

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.col_graph = ColumnGraph(
        root="a",
        columns=[
            ColumnNode(dataset="a", field="x"),
            ColumnNode(dataset="a", field="z"),
            ColumnNode(dataset="b", field="y"),
        ],
        edges=[
            ColumnEdge(source_dataset="a", source_field="x", target_dataset="a", target_field="z"),  # KEEP
            ColumnEdge(
                source_dataset="b", source_field="y", target_dataset="a", target_field="x"
            ),  # source hidden
            ColumnEdge(
                source_dataset="a", source_field="x", target_dataset="b", target_field="y"
            ),  # target hidden
        ],
    )
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_dataset_columns("a", cast(LineageRepository, repo), flt))
    assert [n.dataset for n in result.columns] == ["a", "a"]  # b's column dropped, a's two kept
    # only the both-endpoints-visible edge survives; both leak directions are dropped.
    assert [(e.source_field, e.target_field) for e in result.edges] == [("x", "z")]


def test_get_reconcile_flags_storage_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    # #23: the endpoint wires graph version + on-disk version → drift status. Here the graph says v1 but
    # storage is at v2 (a write that bypassed lineage) → storage_ahead, not in sync.
    from lineage.main import get_reconcile
    from lineage.schemas import ReconcileState

    settings = _settings()  # gating is route-level; the body just compares the two versions
    repo = _FakeRepo()
    repo.write_version = 1
    repo.uri = "s3://lakehouse/silver/features"
    monkeypatch.setattr("lineage.main.read_storage_version", lambda _uri, _opts: 2)
    result = asyncio.run(get_reconcile("silver$features", cast(LineageRepository, repo), settings))
    assert result.status is ReconcileState.STORAGE_AHEAD
    assert result.in_sync is False
    assert (result.graph_version, result.storage_version) == (1, 2)


def test_get_reconcile_skips_storage_read_without_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # No recorded source_uri → we can't read storage, so storage_version is None (graph claims a write
    # with nothing readable behind it) without ever touching the object store.
    from lineage.main import get_reconcile
    from lineage.schemas import ReconcileState

    def _boom(_uri: str, _opts: dict[str, str]) -> int:
        raise AssertionError("storage must not be read when no source_uri is recorded")

    monkeypatch.setattr("lineage.main.read_storage_version", _boom)
    repo = _FakeRepo()
    repo.write_version = 3
    repo.uri = None
    result = asyncio.run(get_reconcile("g$x", cast(LineageRepository, repo), _settings()))
    assert result.status is ReconcileState.MISSING_ON_STORAGE
    assert result.storage_version is None


def test_get_schema_returns_persisted_fields() -> None:
    # #24: the gated /schema endpoint returns the per-version column schema captured at ingest.
    from lineage.main import get_schema

    result = asyncio.run(get_schema("silver$features", cast(LineageRepository, _FakeRepo()), version=2))
    assert result.dataset == "silver$features"
    assert result.version == 2
    assert [f.name for f in result.fields] == ["id"]


def test_get_runs_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22 audit: /runs is governed like /events — a run is shown only if its output datasets are visible.
    from lineage.main import get_runs

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.runs = [RunStatus(run_id="r-a", outputs=["a"]), RunStatus(run_id="r-b", outputs=["b"])]
    flt = auth.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_runs(cast(LineageRepository, repo), flt, settings))
    assert [r.run_id for r in result.runs] == ["r-a"]  # the run that wrote unseen "b" is dropped


def test_ingest_handler_binds_verified_author() -> None:
    from lineage.main import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="attacker")
    asyncio.run(ingest_event(event, cast(LineageRepository, repo), _token("real-user")))
    assert repo.ingested is not None and repo.ingested.author == "real-user"  # body claim overridden


def test_ingest_handler_keeps_body_author_when_oidc_off() -> None:
    from lineage.main import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="claimed")
    asyncio.run(ingest_event(event, cast(LineageRepository, repo), None))
    assert repo.ingested is not None and repo.ingested.author == "claimed"
