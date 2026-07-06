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
from lineage.api import fga_deps, security
from lineage.core.config import LineageSettings
from lineage.models import RunEvent
from lineage.schemas import (
    ColumnEdge,
    ColumnGraph,
    ColumnNeighbors,
    ColumnNode,
    ColumnRef,
    DatasetRef,
    DatasetSchema,
    EventRecord,
    GraphEdge,
    GraphNode,
    LineageGraph,
    Neighbors,
    Runs,
    RunStatus,
    SchemaField,
)
from lineage.services.repository import LineageRepository
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


def test_fga_enabled_without_store_and_model_is_valid() -> None:
    # store_id/model_id are OPTIONAL — main.py provisions the store by NAME at boot when they are absent
    # (idempotent convergence on the catalog's store). Requiring them here would (and did) crash the lineage
    # pod in governed mode, since the chart can't know the runtime-provisioned ids at template time.
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance", fga_enabled=True)
    assert settings.fga_enabled and settings.fga_store_id is None and settings.fga_model_id is None


def test_full_auth_config_is_valid() -> None:
    assert _settings(**_FULL_AUTH).fga_object_type == "table"


# --------------------------------------------------------------------------- #
# authenticate (authn)
# --------------------------------------------------------------------------- #


def test_authenticate_disabled_returns_none() -> None:
    assert security.authenticate(_request(), _settings(), None) is None


def test_authenticate_enabled_missing_token_raises() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    verifier = SimpleNamespace(verify=lambda _t: _token())
    with pytest.raises(UnauthenticatedError):
        security.authenticate(_request(oidc=verifier), settings, None)


def test_authenticate_enabled_unwired_verifier_fails_closed() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    with pytest.raises(ServiceUnavailableError):
        security.authenticate(_request(), settings, _creds())


def test_authenticate_enabled_verifies_token() -> None:
    settings = _settings(oidc_enabled=True, oidc_issuer=_ISSUER, oidc_audience="lance")
    verifier = SimpleNamespace(verify=lambda _t: _token("dee"))
    token = security.authenticate(_request(oidc=verifier), settings, _creds())
    assert token is not None and token.sub == "dee"


# --------------------------------------------------------------------------- #
# require_metadata_access (read authz gate)
# --------------------------------------------------------------------------- #


def test_gate_disabled_allows() -> None:
    # FGA off → no check, no raise (dev/test default, like the catalog).
    asyncio.run(fga_deps.require_metadata_access("a$b", _request(), _settings(), None))


def test_gate_unwired_client_fails_closed() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(fga_deps.require_metadata_access("a$b", _request(), _settings(**_FULL_AUTH), _token()))


def test_gate_unauthenticated_raises() -> None:
    with pytest.raises(UnauthenticatedError):
        asyncio.run(
            fga_deps.require_metadata_access("a$b", _request(fga=object()), _settings(**_FULL_AUTH), None)
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
            fga_deps.require_metadata_access("a$b", _request(fga=client), _settings(**_FULL_AUTH), _token())
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
        fga_deps.require_metadata_access("a$b", _request(fga=client), _settings(**_FULL_AUTH), _token("dee"))
    )
    # The dataset name is gated as table:<name> with the catalog's metadata-read relation.
    assert captured == {"user": "dee", "relation": "can_get_metadata", "obj": "table:a$b"}


# --------------------------------------------------------------------------- #
# enforce_author (provenance forgery prevention)
# --------------------------------------------------------------------------- #


def _event(claimed_author: str = "anon", outputs: list[str] | None = None) -> RunEvent:
    return RunEvent.model_validate(
        {
            "eventType": "COMPLETE",
            "eventTime": "2026-06-24T00:00:00Z",
            "run": {"runId": "r1", "facets": {"author": {"name": claimed_author}}},
            "job": {"namespace": "jobs", "name": "promote"},
            "outputs": [{"namespace": "silver", "name": n} for n in (outputs or [])],
        }
    )


def test_enforce_author_overrides_body_claim() -> None:
    event = _event(claimed_author="attacker")
    fga_deps.enforce_author(event, _token("real-user"))
    assert event.author == "real-user"  # body claim is overwritten by the verified subject


def test_enforce_author_keeps_body_when_unauthenticated() -> None:
    event = _event(claimed_author="claimed")
    fga_deps.enforce_author(event, None)  # OIDC off (dev) → body author preserved
    assert event.author == "claimed"


# --------------------------------------------------------------------------- #
# Route wiring — the gate is actually attached to the endpoints
# --------------------------------------------------------------------------- #


def _api_routes(app: Any) -> list[APIRoute]:
    """Flatten the app's routes, resolving starlette 1.3's lazy ``_IncludedRouter`` wrappers — the lineage
    routes now live under ``include_router``, not directly on ``app.routes`` as when main.py was flat."""
    out: list[APIRoute] = []
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, APIRoute):
            out.append(route)
        elif hasattr(route, "original_router"):
            stack.extend(route.original_router.routes)
        elif hasattr(route, "routes"):
            stack.extend(route.routes)
    return out


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
    for route in _api_routes(app):
        if route.path in gated:
            calls = [d.call for d in route.dependant.dependencies]
            assert fga_deps.require_metadata_access in calls, route.path
            assert fga_deps.audit_read in calls, route.path  # #6: every gated read is also audited
            seen.add(route.path)
    assert seen == gated  # every per-dataset read is present and gated


def test_ingest_route_requires_authentication() -> None:
    from lineage.main import app

    ingest = next(r for r in _api_routes(app) if r.path == "/api/v1/lineage")
    calls = [d.call for d in ingest.dependant.dependencies]
    assert security.authenticate in calls


# --------------------------------------------------------------------------- #
# DatasetFilter — transitive-disclosure filtering (audit w8u4rc2tg, security medium)
# --------------------------------------------------------------------------- #


def test_filter_passthrough_when_fga_off() -> None:
    flt = fga_deps.DatasetFilter(_request(), _settings(), None)
    assert asyncio.run(flt.visible(["a", "b"])) == {"a", "b"}


def test_filter_empty_names_skips_check() -> None:
    flt = fga_deps.DatasetFilter(_request(fga=object()), _settings(**_FULL_AUTH), _token())
    assert asyncio.run(flt.visible([])) == set()


async def _batch_allow_a(_client: object, *, objects: list[str], **_kw: object) -> dict[str, bool]:
    """Fake batch_check: only ``table:a`` is visible."""
    return {o: o == "table:a" for o in objects}


def test_filter_drops_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    flt = fga_deps.DatasetFilter(
        _request(fga=cast(OpenFgaClient, object())), _settings(**_FULL_AUTH), _token()
    )
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
        self.lineage_graph: LineageGraph | None = None

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

    async def graph(self, name: str) -> LineageGraph:
        return self.lineage_graph or LineageGraph(root=name, nodes=[], edges=[])

    async def upstream(self, name: str) -> Neighbors:
        return Neighbors(dataset=name, related=[DatasetRef(name="a"), DatasetRef(name="b")])


def test_get_upstream_drops_unauthorized_related(monkeypatch: pytest.MonkeyPatch) -> None:
    from lineage.api.v1.endpoints.datasets import get_upstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    flt = fga_deps.DatasetFilter(
        _request(fga=cast(OpenFgaClient, object())), _settings(**_FULL_AUTH), _token()
    )
    result = asyncio.run(get_upstream("root", cast(LineageRepository, _FakeRepo()), flt))
    assert [ref.name for ref in result.related] == ["a"]  # "b" is filtered out


def test_get_events_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22: the durable events feed is governed — drop events referencing a dataset the caller can't see.
    from lineage.api.v1.endpoints.runs import get_events

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.events = [
        EventRecord(seq=2, outputs=["a"], inputs=[], event={}),
        EventRecord(seq=1, outputs=["b"], inputs=[], event={}),  # "b" not visible → dropped
    ]
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_events(cast(LineageRepository, repo), flt, settings))
    assert [e.outputs for e in result.events] == [["a"]]  # the "b" event is filtered out


def test_get_events_hides_dataset_less_events_when_governed(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22 audit: a dataset-less event (empty inputs+outputs) must NOT pass the gate vacuously when FGA is
    # on — it would otherwise leak the run/author/full event JSON to a caller with zero grants.
    from lineage.api.v1.endpoints.runs import get_events

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.events = [EventRecord(seq=1, outputs=[], inputs=[], event={"run": {"runId": "secret"}})]
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_events(cast(LineageRepository, repo), flt, settings))
    assert result.events == []  # dataset-less event is hidden under governance


def test_get_column_upstream_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #24: column provenance is governed — a related column in a dataset the caller can't see is dropped
    # (a column has no ACL of its own; it inherits its owning table's visibility).
    from lineage.api.v1.endpoints.columns import get_column_upstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.col_related = [ColumnRef(dataset="a", field="x"), ColumnRef(dataset="b", field="y")]
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_column_upstream("a", "root", cast(LineageRepository, repo), flt, settings))
    assert [(r.dataset, r.field) for r in result.related] == [("a", "x")]  # b's column is hidden


def test_get_column_downstream_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #24: column IMPACT is governed identically to provenance — a related column in a hidden dataset drops.
    from lineage.api.v1.endpoints.columns import get_column_downstream

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)  # only "a" visible
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.col_related = [ColumnRef(dataset="a", field="x"), ColumnRef(dataset="b", field="y")]
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_column_downstream("a", "root", cast(LineageRepository, repo), flt, settings))
    assert [(r.dataset, r.field) for r in result.related] == [("a", "x")]  # b's column is hidden


def test_get_graph_drops_hidden_nodes_and_edges_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dataset-level /graph transitive-disclosure guarantee (the contract the column tests cite as
    # "same as /graph"): a node the caller can't see is dropped, and an edge needs BOTH endpoints visible
    # — proven in both leak directions (source-hidden AND target-hidden). The requested root rides on the
    # route gate's authorization, so the filter must keep it WITHOUT re-checking it (visible() is called
    # with the other nodes only).
    from lineage.api.v1.endpoints.datasets import get_graph

    checked: list[str] = []

    async def _allow_c(_client: object, *, objects: list[str], **_kw: object) -> dict[str, bool]:
        checked.extend(objects)
        return {o: o == "table:c" for o in objects}

    monkeypatch.setattr(fga, "batch_check", _allow_c)
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.lineage_graph = LineageGraph(
        root="a",
        nodes=[GraphNode(id="a"), GraphNode(id="b"), GraphNode(id="c")],
        edges=[
            GraphEdge(source="a", target="c"),  # KEEP: both endpoints visible
            GraphEdge(source="b", target="a"),  # source hidden
            GraphEdge(source="a", target="b"),  # target hidden
        ],
    )
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_graph("a", cast(LineageRepository, repo), flt))
    assert {n.id for n in result.nodes} == {"a", "c"}  # b dropped; the root kept without an FGA check
    assert "table:a" not in checked  # the root was NOT re-checked (the route gate already authorized it)
    assert [(e.source, e.target) for e in result.edges] == [("a", "c")]  # both leak directions dropped


def test_get_dataset_columns_drops_edges_touching_hidden_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #24: the column-graph view drops nodes/edges touching a dataset the caller can't see. An edge needs
    # BOTH endpoints visible — a 3-edge fixture proves selectivity in BOTH leak directions (source-hidden
    # AND target-hidden), not just one — same transitive-disclosure guarantee as /graph, at column res.
    from lineage.api.v1.endpoints.columns import get_dataset_columns

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
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_dataset_columns("a", cast(LineageRepository, repo), flt))
    assert [n.dataset for n in result.columns] == ["a", "a"]  # b's column dropped, a's two kept
    # only the both-endpoints-visible edge survives; both leak directions are dropped.
    assert [(e.source_field, e.target_field) for e in result.edges] == [("x", "z")]


def test_get_reconcile_flags_storage_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    # #23: the endpoint wires graph version + on-disk version → drift status. Here the graph says v1 but
    # storage is at v2 (a write that bypassed lineage) → storage_ahead, not in sync.
    from lineage.api.v1.endpoints.reconcile import get_reconcile
    from lineage.schemas import ReconcileState

    settings = _settings()  # gating is route-level; the body just compares the two versions
    repo = _FakeRepo()
    repo.write_version = 1
    repo.uri = "s3://lakehouse/silver/features"
    monkeypatch.setattr("lineage.api.v1.endpoints.reconcile.read_storage_version", lambda _uri, _opts: 2)
    result = asyncio.run(get_reconcile("silver$features", cast(LineageRepository, repo), settings))
    assert result.status is ReconcileState.STORAGE_AHEAD
    assert result.in_sync is False
    assert (result.graph_version, result.storage_version) == (1, 2)


def test_get_reconcile_skips_storage_read_without_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # No recorded source_uri → we can't read storage, so storage_version is None (graph claims a write
    # with nothing readable behind it) without ever touching the object store.
    from lineage.api.v1.endpoints.reconcile import get_reconcile
    from lineage.schemas import ReconcileState

    def _boom(_uri: str, _opts: dict[str, str]) -> int:
        raise AssertionError("storage must not be read when no source_uri is recorded")

    monkeypatch.setattr("lineage.api.v1.endpoints.reconcile.read_storage_version", _boom)
    repo = _FakeRepo()
    repo.write_version = 3
    repo.uri = None
    result = asyncio.run(get_reconcile("g$x", cast(LineageRepository, repo), _settings()))
    assert result.status is ReconcileState.MISSING_ON_STORAGE
    assert result.storage_version is None


def test_get_schema_returns_persisted_fields() -> None:
    # #24: the gated /schema endpoint returns the per-version column schema captured at ingest.
    from lineage.api.v1.endpoints.datasets import get_schema

    result = asyncio.run(get_schema("silver$features", cast(LineageRepository, _FakeRepo()), version=2))
    assert result.dataset == "silver$features"
    assert result.version == 2
    assert [f.name for f in result.fields] == ["id"]


def test_get_runs_filters_to_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    # #22 audit: /runs is governed like /events — a run is shown only if its output datasets are visible.
    from lineage.api.v1.endpoints.runs import get_runs

    monkeypatch.setattr(fga, "batch_check", _batch_allow_a)
    settings = _settings(**_FULL_AUTH)
    repo = _FakeRepo()
    repo.runs = [RunStatus(run_id="r-a", outputs=["a"]), RunStatus(run_id="r-b", outputs=["b"])]
    flt = fga_deps.DatasetFilter(_request(fga=cast(OpenFgaClient, object())), settings, _token())
    result = asyncio.run(get_runs(cast(LineageRepository, repo), flt, settings))
    assert [r.run_id for r in result.runs] == ["r-a"]  # the run that wrote unseen "b" is dropped


def test_ingest_handler_binds_verified_author() -> None:
    from lineage.api.v1.endpoints.ingest import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="attacker")
    asyncio.run(
        ingest_event(event, _request(), cast(LineageRepository, repo), _settings(), _token("real-user"))
    )
    assert repo.ingested is not None and repo.ingested.author == "real-user"  # body claim overridden


def test_ingest_handler_keeps_body_author_when_oidc_off() -> None:
    from lineage.api.v1.endpoints.ingest import ingest_event

    repo = _FakeRepo()
    event = _event(claimed_author="claimed")
    asyncio.run(ingest_event(event, _request(), cast(LineageRepository, repo), _settings(), None))
    assert repo.ingested is not None and repo.ingested.author == "claimed"


# --------------------------------------------------------------------------- #
# #2 — output-scoped ingest authz: a producer may only record provenance for
# outputs it can WRITE (can_write_data), not just that it's authenticated.
# --------------------------------------------------------------------------- #


def test_output_authz_disabled_is_noop() -> None:
    # FGA off → no check (dev/test default).
    asyncio.run(fga_deps.enforce_output_authz(_event(outputs=["a$b"]), _request(), _settings(), None))


def test_output_authz_no_outputs_is_noop() -> None:
    # An event with no outputs makes no write claim → nothing to authorize.
    asyncio.run(
        fga_deps.enforce_output_authz(
            _event(outputs=[]), _request(fga=object()), _settings(**_FULL_AUTH), _token()
        )
    )


def test_output_authz_unwired_client_fails_closed() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga_deps.enforce_output_authz(
                _event(outputs=["a$b"]), _request(), _settings(**_FULL_AUTH), _token()
            )
        )


def test_output_authz_unauthenticated_raises() -> None:
    with pytest.raises(UnauthenticatedError):
        asyncio.run(
            fga_deps.enforce_output_authz(
                _event(outputs=["a$b"]), _request(fga=object()), _settings(**_FULL_AUTH), None
            )
        )


def test_output_authz_denies_non_writable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # alice may write a$b but NOT c$d → the whole ingest is denied (403).
    async def _batch(_client: object, *, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        return {o: (o == "table:a$b") for o in objects}

    monkeypatch.setattr(fga, "batch_check", _batch)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(
            fga_deps.enforce_output_authz(
                _event(outputs=["a$b", "c$d"]),
                _request(fga=cast(OpenFgaClient, object())),
                _settings(**_FULL_AUTH),
                _token(),
            )
        )


def test_output_authz_allows_when_all_outputs_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _batch(_client: object, *, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        captured.update(user=user, relation=relation, objects=sorted(objects))
        return dict.fromkeys(objects, True)

    monkeypatch.setattr(fga, "batch_check", _batch)
    asyncio.run(
        fga_deps.enforce_output_authz(
            _event(outputs=["a$b"]),
            _request(fga=cast(OpenFgaClient, object())),
            _settings(**_FULL_AUTH),
            _token(),
        )
    )
    # The write check is on the right subject/relation/objects, not just "some" allow.
    assert captured == {"user": "alice", "relation": "can_write_data", "objects": ["table:a$b"]}


# --------------------------------------------------------------------------- #
# #5 — durable /events feed retention (prune older rows past the cap on ingest).
# --------------------------------------------------------------------------- #


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))


class _FakePool:
    """Minimal async pool whose ``connection()`` yields a recording fake conn (no DB)."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def connection(self) -> Any:
        conn = self._conn

        class _Ctx:
            async def __aenter__(self) -> _FakeConn:
                return conn

            async def __aexit__(self, *_a: object) -> bool:
                return False

        return _Ctx()


def _record(repo: LineageRepository) -> None:
    asyncio.run(
        repo.record_event(
            run_id="r",
            event_type="COMPLETE",
            event_time="t",
            job="j",
            author="a",
            inputs=[],
            outputs=["x"],
            event={},
        )
    )


def test_events_retention_prunes_when_set() -> None:
    conn = _FakeConn()
    repo = LineageRepository(cast(Any, _FakePool(conn)), "g", events_retention=5)
    _record(repo)
    assert any("INSERT INTO public.lineage_events" in s for s, _ in conn.calls)
    prune = [p for s, p in conn.calls if "DELETE FROM public.lineage_events" in s]
    assert prune == [(5,)]  # exactly one prune, parameterized with the retention cap


def test_events_retention_unbounded_does_not_prune() -> None:
    conn = _FakeConn()
    repo = LineageRepository(cast(Any, _FakePool(conn)), "g", events_retention=0)
    _record(repo)
    assert not any("DELETE FROM public.lineage_events" in s for s, _ in conn.calls)


# --------------------------------------------------------------------------- #
# #6 — read-audit: log WHO read which dataset on a gated read. Off by default; needs a verified
# subject; best-effort (an audit-write failure must never fail the read it is auditing).
# --------------------------------------------------------------------------- #


class _AuditRepo:
    """Repository stub capturing record_read calls (and able to raise, to prove best-effort)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.reads: list[tuple[str, str]] = []
        self._fail = fail

    async def record_read(self, *, reader: str, dataset: str) -> None:
        if self._fail:
            raise RuntimeError("audit store down")
        self.reads.append((reader, dataset))


def test_audit_read_disabled_does_not_record() -> None:
    # Off by default → not even an authenticated read writes an audit row.
    repo = _AuditRepo()
    asyncio.run(fga_deps.audit_read("a$b", _settings(), _token(), cast(LineageRepository, repo)))
    assert repo.reads == []


def test_audit_read_unauthenticated_does_not_record() -> None:
    # Enabled but no verified subject (OIDC off) → nothing to attribute, so no row.
    repo = _AuditRepo()
    asyncio.run(
        fga_deps.audit_read("a$b", _settings(read_audit_enabled=True), None, cast(LineageRepository, repo))
    )
    assert repo.reads == []


def test_audit_read_records_reader_and_dataset_when_enabled() -> None:
    # The audit row is keyed by the VERIFIED subject + the dataset name — who read what.
    repo = _AuditRepo()
    asyncio.run(
        fga_deps.audit_read(
            "silver$features",
            _settings(read_audit_enabled=True),
            _token("dee"),
            cast(LineageRepository, repo),
        )
    )
    assert repo.reads == [("dee", "silver$features")]


def test_audit_read_best_effort_swallows_store_failure() -> None:
    # An audit-write failure must NEVER fail the read it is auditing — the call returns, does not raise.
    repo = _AuditRepo(fail=True)
    asyncio.run(
        fga_deps.audit_read(
            "a$b", _settings(read_audit_enabled=True), _token(), cast(LineageRepository, repo)
        )
    )
