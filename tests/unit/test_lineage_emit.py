"""Unit tests for catalog → lineage emission (P0 #3, ``catalog.core.lineage_emit``).

Infra-free: the pure event builder is checked directly, the HTTP emitter is exercised with a
fake client (best-effort: it must swallow failures), and a round-trip pins the wire contract
the lineage service ingests (``RunEvent`` parses the emitted event; the ``create_table``
operation string is shared by both sides).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
from catalog.core.lineage_emit import (
    CREATE_TABLE,
    DROP_TABLE,
    INSERT,
    MERGE_INSERT,
    DaprEmitter,
    HttpLineageEmitter,
    LineageEmitter,
    NoopEmitter,
    build_write_event,
    emit_write_event,
    make_emitter,
)
from lineage.models import RunEvent
from lineage.services.repository import _CREATE_TABLE_OP


def test_build_create_event_shape() -> None:
    # The create event is build_write_event with operation=create_table (the real production path —
    # emit_create → emit_write → build_write_event); this pins that shape.
    event = build_write_event(
        table_id="alpha$bronze$images",
        namespace="alpha$bronze",
        author="alice",
        version=1,
        operation=CREATE_TABLE,
        run_id="r1",
        event_time="2026-06-24T00:00:00+00:00",
        job_namespace="lance-catalog",
    )
    assert event["eventType"] == "COMPLETE"
    output = event["outputs"][0]
    assert output["namespace"] == "alpha$bronze"
    assert output["name"] == "alpha$bronze$images"
    # #20: the standard version facet rides the output so the WROTE edge carries the Lance version.
    assert output["facets"]["version"]["datasetVersion"] == "1"
    # Custom facets carry the spec-required _producer + _schemaURL alongside their payload.
    author = event["run"]["facets"]["author"]
    assert author["name"] == "alice" and author["sub"] == "alice"
    assert author["_producer"] and author["_schemaURL"]
    lance = event["run"]["facets"]["lance"]
    assert lance["operation"] == "create_table" and lance["version"] == 1
    assert lance["_producer"] and lance["_schemaURL"]
    # Top-level schemaURL is present (spec-required on every RunEvent).
    assert event["schemaURL"]
    # Per-table job identity (not the bare op) so one table's writes don't lump into a shared Job node.
    assert event["job"] == {"namespace": "lance-catalog", "name": "create_table.alpha$bronze$images"}


def test_build_create_event_without_author_omits_facet() -> None:
    event = build_write_event(
        table_id="t",
        namespace="",
        author=None,
        version=1,
        operation=CREATE_TABLE,
        run_id="r1",
        event_time="t",
        job_namespace="lance-catalog",
    )
    assert "author" not in event["run"]["facets"]
    assert event["run"]["facets"]["lance"]["operation"] == "create_table"


def test_create_table_operation_string_is_shared() -> None:
    # The catalog emitter and the lineage repository must agree on the facet operation string.
    assert CREATE_TABLE == _CREATE_TABLE_OP == "create_table"


def test_emitted_event_round_trips_into_lineage_model() -> None:
    """The event the catalog emits must parse in the lineage service's RunEvent model."""
    event = build_write_event(
        table_id="alpha$bronze$images",
        namespace="alpha$bronze",
        author="alice",
        version=1,
        operation=CREATE_TABLE,
        run_id="r1",
        event_time="2026-06-24T00:00:00+00:00",
        job_namespace="lance-catalog",
    )
    parsed = RunEvent.model_validate(event)
    assert parsed.operation == "create_table"
    assert parsed.author == "alice"
    assert parsed.outputs[0].name == "alpha$bronze$images"
    # #20: the version the lineage service folds onto the WROTE edge (was None before this fix).
    assert parsed.output_version("alpha$bronze$images") == "1"


def test_noop_emitter_does_nothing() -> None:
    assert asyncio.run(NoopEmitter().emit_create(table_id="t", namespace="", author=None, version=1)) is None


class _Resp:
    def raise_for_status(self) -> None:
        return None


class _CapturingClient:
    """Fake httpx client capturing the posted JSON + headers."""

    def __init__(self) -> None:
        self.posted: Any = None
        self.headers: Any = None

    async def post(self, *_args: object, **kwargs: object) -> _Resp:
        self.posted = kwargs["json"]
        self.headers = kwargs.get("headers")
        return _Resp()


class _BoomClient:
    async def post(self, *_args: object, **_kwargs: object) -> _Resp:
        raise httpx.ConnectError("lineage down")


def test_http_emitter_posts_the_event() -> None:
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage/api/v1/lineage", job_namespace="lance-catalog"
    )
    asyncio.run(emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=3))
    assert client.posted is not None
    output = client.posted["outputs"][0]
    assert output["namespace"] == "a"
    assert output["name"] == "a$b"
    assert output["facets"]["version"]["datasetVersion"] == "3"  # #20
    assert client.posted["run"]["facets"]["author"]["sub"] == "alice"


def test_http_emitter_uses_shared_run_id() -> None:
    # #21: the catalog passes the same run id it stamped into the Lance file, so the file points at
    # its exact creating run in the lineage graph.
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage/api/v1/lineage", job_namespace="lance-catalog"
    )
    asyncio.run(
        emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=1, run_id="r-shared")
    )
    assert client.posted is not None
    assert client.posted["run"]["runId"] == "r-shared"


def test_http_emitter_forwards_authorization() -> None:
    # So ingest accepts the event when the lineage service has OIDC on (else 401 + silent drop).
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage", job_namespace="lance-catalog"
    )
    asyncio.run(
        emitter.emit_create(
            table_id="a$b", namespace="a", author="alice", version=1, authorization="Bearer xyz"
        )
    )
    assert client.headers == {"Authorization": "Bearer xyz"}


# --------------------------------------------------------------------------- #
# emit_write_event — the shared INLINE-await helper (durability: not BackgroundTasks)
# --------------------------------------------------------------------------- #


class _RecordingEmitter:
    """Records the emit_write call kwargs (stands in for the real emitter)."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def emit_write(self, **kwargs: Any) -> None:
        self.writes.append(kwargs)


def test_emit_write_event_maps_segments_to_canonical_ids_and_awaits_inline() -> None:
    em = _RecordingEmitter()
    asyncio.run(
        emit_write_event(
            cast(LineageEmitter, em),
            ["db1", "users"],
            delimiter="$",
            author="alice",
            version=3,
            operation="update",
            authorization="Bearer x",
        )
    )
    # Awaited inline → exactly one recorded call (not deferred via BackgroundTasks, not dropped).
    assert len(em.writes) == 1
    w = em.writes[0]
    assert w["table_id"] == "db1$users"  # canonical delimited id == the OpenFGA object id == the catalog id
    assert w["namespace"] == "db1"  # parent namespace
    assert w["operation"] == "update"
    assert w["version"] == 3
    assert w["author"] == "alice"
    assert w["authorization"] == "Bearer x"
    assert w["run_id"]  # a fresh run id is generated per emit


def test_emit_write_event_root_table_has_empty_namespace() -> None:
    # Boundary: a top-level (single-segment) table has no parent namespace → "".
    em = _RecordingEmitter()
    asyncio.run(
        emit_write_event(
            cast(LineageEmitter, em),
            ["t"],
            delimiter="$",
            author=None,
            version=None,
            operation=INSERT,
            authorization=None,
        )
    )
    assert em.writes[0]["namespace"] == ""
    assert em.writes[0]["version"] is None


def test_build_write_event_drop_is_versionless_and_named_drop_table() -> None:
    # #7a: a drop records a VERSIONLESS run named drop_table — the dataset node persists as history
    # (Marquez keeps dropped datasets too), so a reader can tell it was deleted, not just last-written.
    event = build_write_event(
        table_id="db$t",
        namespace="db",
        author="alice",
        version=None,
        operation=DROP_TABLE,
        run_id="r1",
        event_time="2026-01-01T00:00:00+00:00",
        job_namespace="lance-catalog",
    )
    assert "version" not in event["outputs"][0].get("facets", {})  # no version facet for a drop
    assert event["run"]["facets"]["lance"]["operation"] == "drop_table"
    assert "version" not in event["run"]["facets"]["lance"]
    assert event["job"]["name"] == "drop_table.db$t"


def test_http_emitter_omits_auth_header_when_absent() -> None:
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage", job_namespace="lance-catalog"
    )
    asyncio.run(emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=1))
    assert client.headers is None


def test_http_emitter_swallows_failures() -> None:
    # Best-effort: a down/erroring lineage service must NOT propagate out of a catalog write.
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, _BoomClient()), "http://lineage", job_namespace="lance-catalog"
    )
    asyncio.run(emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=1))  # no raise


def test_make_emitter_selects_implementation() -> None:
    client = cast(httpx.AsyncClient, object())

    def _make(**over: object) -> object:
        kw: dict[str, object] = {
            "enabled": True,
            "transport": "http",
            "url": "http://lineage",
            "client": client,
            "dapr": None,
            "pubsub": "lineage-pubsub",
            "topic": "lineage.events.v1",
            "job_namespace": "lance-catalog",
        }
        kw.update(over)
        return make_emitter(**kw)  # ty: ignore[invalid-argument-type]  # dict[str, object] kwargs fan-out

    assert isinstance(_make(), HttpLineageEmitter)
    assert isinstance(_make(enabled=False), NoopEmitter)  # disabled → no-op
    assert isinstance(_make(url=None), NoopEmitter)  # http transport unwired → no-op
    assert isinstance(_make(transport="dapr", dapr=object()), DaprEmitter)  # durable Dapr transport
    assert isinstance(_make(transport="dapr", dapr=None), NoopEmitter)  # dapr unwired → no-op


class _FakeDapr:
    """Just enough of the async DaprClient to capture a publish_event (or fail one)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[dict[str, Any]] = []
        self._fail = fail

    async def publish_event(
        self, *, pubsub_name: str, topic_name: str, data: str, data_content_type: str
    ) -> None:
        if self._fail:
            raise RuntimeError("sidecar down")
        self.published.append(
            {
                "pubsub": pubsub_name,
                "topic": topic_name,
                "content_type": data_content_type,
                "event": json.loads(data),
            }
        )


def test_dapr_emitter_publishes_event_to_topic() -> None:
    dapr = _FakeDapr()
    emitter = DaprEmitter(
        cast(Any, dapr),
        "lineage-pubsub",
        "lineage.events.v1",
        job_namespace="lance-catalog",
        timeout_seconds=5.0,
    )
    asyncio.run(emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=1, run_id="r-1"))
    assert len(dapr.published) == 1
    pub = dapr.published[0]
    assert pub["pubsub"] == "lineage-pubsub" and pub["topic"] == "lineage.events.v1"
    assert pub["content_type"] == "application/json"
    assert pub["event"]["outputs"][0]["name"] == "a$b"  # the spec-correct OpenLineage event is the data
    assert pub["event"]["run"]["facets"]["author"]["sub"] == "alice"  # the verified catalog author
    assert pub["event"]["run"]["runId"] == "r-1"


def test_dapr_emitter_swallows_publish_failure() -> None:
    # A sidecar/broker outage at publish must never break the catalog write (best-effort, like HTTP).
    emitter = DaprEmitter(
        cast(Any, _FakeDapr(fail=True)),
        "lineage-pubsub",
        "lineage.events.v1",
        job_namespace="x",
        timeout_seconds=5.0,
    )
    asyncio.run(
        emitter.emit_write(table_id="a$b", namespace="a", author=None, version=2, operation=INSERT)
    )  # no raise


# --- #19: lineage on every write (not just create) ---


def test_build_write_event_insert_omits_version_facet() -> None:
    event = build_write_event(
        table_id="a$b",
        namespace="a",
        author="alice",
        version=None,
        operation=INSERT,
        run_id="r1",
        event_time="t",
        job_namespace="lance-catalog",
    )
    assert event["job"]["name"] == "insert.a$b"
    assert event["run"]["facets"]["lance"]["operation"] == "insert"
    assert "version" not in event["run"]["facets"]["lance"]  # no version key on a version-less insert
    assert "facets" not in event["outputs"][0]  # no version facet asserted when version is None


def test_build_write_event_merge_carries_version() -> None:
    event = build_write_event(
        table_id="a$b",
        namespace="a",
        author=None,
        version=4,
        operation=MERGE_INSERT,
        run_id="r1",
        event_time="t",
        job_namespace="lance-catalog",
    )
    assert event["run"]["facets"]["lance"]["operation"] == "merge_insert"
    assert event["run"]["facets"]["lance"]["version"] == 4
    assert event["outputs"][0]["facets"]["version"]["datasetVersion"] == "4"
    assert "author" not in event["run"]["facets"]


def test_write_event_round_trips_into_lineage_model() -> None:
    event = build_write_event(
        table_id="a$b",
        namespace="a",
        author="alice",
        version=None,
        operation=INSERT,
        run_id="r1",
        event_time="2026-06-24T00:00:00+00:00",
        job_namespace="lance-catalog",
    )
    parsed = RunEvent.model_validate(event)
    assert parsed.operation == "insert"
    assert parsed.is_success is True
    assert parsed.output_version("a$b") is None  # an insert asserts no Lance version on the WROTE edge


def test_http_emitter_emit_write_posts_operation_and_version() -> None:
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage/api/v1/lineage", job_namespace="lance-catalog"
    )
    asyncio.run(
        emitter.emit_write(
            table_id="a$b", namespace="a", author="alice", version=4, operation=MERGE_INSERT, run_id="r-9"
        )
    )
    assert client.posted is not None
    assert client.posted["job"]["name"] == "merge_insert.a$b"
    assert client.posted["run"]["runId"] == "r-9"
    assert client.posted["outputs"][0]["facets"]["version"]["datasetVersion"] == "4"
