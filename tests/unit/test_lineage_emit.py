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
    HttpLineageEmitter,
    NoopEmitter,
    build_create_event,
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
    assert event["outputs"] == [{"namespace": "alpha$bronze", "name": "alpha$bronze$images"}]
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


def test_noop_emitter_does_nothing() -> None:
    assert asyncio.run(NoopEmitter().emit_create(table_id="t", namespace="", author=None, version=1)) is None


class _Resp:
    def raise_for_status(self) -> None:
        return None


class _CapturingClient:
    """Fake httpx client capturing the posted JSON."""

    def __init__(self) -> None:
        self.posted: Any = None

    async def post(self, *_args: object, **kwargs: object) -> _Resp:
        self.posted = kwargs["json"]
        return _Resp()


class _BoomClient:
    async def post(self, *_args: object, **_kwargs: object) -> _Resp:
        raise httpx.ConnectError("lineage down")


def test_http_emitter_posts_the_event() -> None:
    client = _CapturingClient()
    emitter = HttpLineageEmitter(
        cast(httpx.AsyncClient, client), "http://lineage/api/v1/lineage", job_namespace="lance-catalog"
    )
    asyncio.run(emitter.emit_create(table_id="a$b", namespace="a", author="alice", version=1))
    assert client.posted is not None
    assert client.posted["outputs"] == [{"namespace": "a", "name": "a$b"}]
    assert client.posted["run"]["facets"]["author"]["sub"] == "alice"


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
