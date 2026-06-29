"""Unit tests for catalog → lineage emission (P0 #3, ``app.core.lineage_emit``).

Infra-free: the pure event builder is checked directly, the HTTP emitter is exercised with a
fake client (best-effort: it must swallow failures), and a round-trip pins the wire contract
the lineage service ingests (``RunEvent`` parses the emitted event; the ``create_table``
operation string is shared by both sides).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from app.core.lineage_emit import (
    CREATE_TABLE,
    INSERT,
    MERGE_INSERT,
    HttpLineageEmitter,
    NoopEmitter,
    build_create_event,
    build_write_event,
    make_emitter,
)
from lineage.models import RunEvent
from lineage.repository import _CREATE_TABLE_OP


def test_build_create_event_shape() -> None:
    event = build_create_event(
        table_id="alpha$bronze$images",
        namespace="alpha$bronze",
        author="alice",
        version=1,
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
    assert event["run"]["facets"]["author"] == {"name": "alice", "sub": "alice"}
    assert event["run"]["facets"]["lance"] == {"operation": "create_table", "version": 1}
    assert event["job"] == {"namespace": "lance-catalog", "name": "create_table"}


def test_build_create_event_without_author_omits_facet() -> None:
    event = build_create_event(
        table_id="t",
        namespace="",
        author=None,
        version=1,
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
    event = build_create_event(
        table_id="alpha$bronze$images",
        namespace="alpha$bronze",
        author="alice",
        version=1,
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
    assert isinstance(
        make_emitter(enabled=True, url="http://lineage", client=client, job_namespace="lance-catalog"),
        HttpLineageEmitter,
    )
    assert isinstance(
        make_emitter(enabled=False, url="http://lineage", client=client, job_namespace="x"), NoopEmitter
    )
    assert isinstance(make_emitter(enabled=True, url=None, client=client, job_namespace="x"), NoopEmitter)


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
    assert event["job"]["name"] == "insert"
    assert event["run"]["facets"]["lance"] == {"operation": "insert"}  # no version key
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
    assert event["run"]["facets"]["lance"] == {"operation": "merge_insert", "version": 4}
    assert event["outputs"][0]["facets"]["version"]["datasetVersion"] == "4"
    assert "author" not in event["run"]["facets"]


def test_create_event_is_a_write_event_with_create_operation() -> None:
    via_create = build_create_event(
        table_id="t", namespace="", author="a", version=1, run_id="r", event_time="t", job_namespace="j"
    )
    via_write = build_write_event(
        table_id="t",
        namespace="",
        author="a",
        version=1,
        operation=CREATE_TABLE,
        run_id="r",
        event_time="t",
        job_namespace="j",
    )
    assert via_create == via_write


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
    assert client.posted["job"]["name"] == "merge_insert"
    assert client.posted["run"]["runId"] == "r-9"
    assert client.posted["outputs"][0]["facets"]["version"]["datasetVersion"] == "4"
