"""Unit tests for compaction → lineage emission (#7b) — infra-free (no Dapr, no S3, no Lance).

Drives the async emit with stdlib ``asyncio.run`` (the project convention). Covers:
* the table-id parse from the catalog's ``<uuid>_<table_id>`` layout (incl. the boundaries),
* the OpenLineage maintenance-event shape **round-tripped through the lineage ``RunEvent`` model** — the
  cross-service wire contract (a successful, versionless, input-less run on the dataset),
* which datasets in a sweep get a maintenance event (material work only; errored / no-op / unparseable
  skipped) + the parent-namespace derivation,
* the emitter factory (no-op when off/unwired; Dapr when wired) and the best-effort publish (a broker
  outage must never fail a sweep).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from compaction.core.lineage_emit import (
    COMPACTION,
    DaprMaintenanceEmitter,
    NoopEmitter,
    build_maintenance_event,
    make_emitter,
    table_id_from_uri,
)
from compaction.services.optimize import DatasetResult
from compaction.services.sweep import emit_sweep_lineage
from lineage.models import RunEvent

# --------------------------------------------------------------------------- #
# table_id parse from the catalog's <uuid>_<table_id> dataset layout
# --------------------------------------------------------------------------- #


def test_table_id_from_uri_splits_on_first_underscore() -> None:
    # The catalog lays a table out as s3://<bucket>/<uuid>_<table_id>; the id may itself contain '$'.
    assert table_id_from_uri("s3://lance-catalog/abcd_ns$table") == "ns$table"


def test_table_id_from_uri_keeps_later_underscores_in_id() -> None:
    # Only the FIRST '_' separates the uuid from the id — an id containing '_' survives intact.
    assert table_id_from_uri("s3://lance-catalog/uuid_my_table") == "my_table"


def test_table_id_from_uri_tolerates_trailing_slash() -> None:
    assert table_id_from_uri("s3://lance-catalog/abcd_gold$catalog/") == "gold$catalog"


def test_table_id_from_uri_none_without_underscore() -> None:
    # A directory that isn't the <uuid>_<id> layout yields no id → no bogus maintenance event.
    assert table_id_from_uri("s3://lance-catalog/manifestlike") is None


# --------------------------------------------------------------------------- #
# maintenance event shape + the cross-service wire contract
# --------------------------------------------------------------------------- #


def test_build_maintenance_event_shape() -> None:
    event = build_maintenance_event(
        table_id="ns$table",
        namespace="ns",
        job_namespace="compaction",
        run_id="r1",
        event_time="2026-06-30T00:00:00Z",
    )
    assert event["run"]["facets"]["lance"]["operation"] == COMPACTION
    assert event["outputs"] == [{"namespace": "ns", "name": "ns$table"}]
    assert event["inputs"] == []
    # Versionless: a maintenance pass asserts no data version, so no output facets at all.
    assert "facets" not in event["outputs"][0]


def test_maintenance_event_round_trips_through_lineage_run_event() -> None:
    # The wire contract: the lineage service must parse a compaction event as a successful, versionless,
    # input-less run on the dataset — so it records a WROTE with no version + no DERIVED_FROM (no inputs).
    event = build_maintenance_event(
        table_id="silver$features",
        namespace="silver",
        job_namespace="compaction",
        run_id="r2",
        event_time="2026-06-30T00:00:00Z",
    )
    parsed = RunEvent.model_validate(event)
    assert parsed.is_success
    assert parsed.operation == COMPACTION
    assert [d.name for d in parsed.outputs] == ["silver$features"]
    assert parsed.inputs == []
    assert parsed.output_version("silver$features") is None  # versionless on the WROTE edge


# --------------------------------------------------------------------------- #
# per-sweep emit selection
# --------------------------------------------------------------------------- #


class _RecordingEmitter:
    """Captures (table_id, namespace) for each maintenance event emitted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def emit_maintenance(self, *, table_id: str, namespace: str) -> None:
        self.calls.append((table_id, namespace))


def _result(uri: str, **kw: Any) -> DatasetResult:
    return DatasetResult(uri=uri, **kw)


def test_emit_sweep_lineage_emits_only_for_materially_compacted_datasets() -> None:
    emitter = _RecordingEmitter()
    results = [
        _result("s3://b/u1_ns$a", fragments_removed=3),  # compacted → emit
        _result("s3://b/u2_ns$b", old_versions_removed=2),  # GC'd → emit
        _result("s3://b/u3_ns$c"),  # no-op tick → skip
        _result("s3://b/u4_ns$d", fragments_removed=1, error="boom"),  # errored → skip
        _result("s3://b/nounderscore", fragments_removed=1),  # unparseable id → skip
    ]
    asyncio.run(emit_sweep_lineage(cast(Any, emitter), results, delimiter="$"))
    assert emitter.calls == [("ns$a", "ns"), ("ns$b", "ns")]


def test_emit_sweep_lineage_root_table_has_empty_namespace() -> None:
    # A single-segment table id has no parent namespace → "" (matching the catalog's create emit, so the
    # maintenance event never clobbers the dataset node's namespace).
    emitter = _RecordingEmitter()
    asyncio.run(
        emit_sweep_lineage(
            cast(Any, emitter), [_result("s3://b/uuid_solo", fragments_removed=1)], delimiter="$"
        )
    )
    assert emitter.calls == [("solo", "")]


# --------------------------------------------------------------------------- #
# emitter factory + transport behavior
# --------------------------------------------------------------------------- #


def test_make_emitter_noop_when_disabled() -> None:
    emitter = make_emitter(enabled=False, dapr=None, pubsub="p", topic="t", job_namespace="compaction")
    assert isinstance(emitter, NoopEmitter)


def test_make_emitter_noop_when_enabled_but_unwired() -> None:
    # Enabled but no Dapr client → stay a no-op rather than silently publish nowhere (fail safe).
    emitter = make_emitter(enabled=True, dapr=None, pubsub="p", topic="t", job_namespace="compaction")
    assert isinstance(emitter, NoopEmitter)


def test_make_emitter_dapr_when_enabled_and_wired() -> None:
    emitter = make_emitter(
        enabled=True,
        dapr=cast(Any, object()),
        pubsub="lineage-pubsub",
        topic="lineage.events.v1",
        job_namespace="compaction",
    )
    assert isinstance(emitter, DaprMaintenanceEmitter)


def test_noop_emitter_does_nothing() -> None:
    asyncio.run(NoopEmitter().emit_maintenance(table_id="ns$a", namespace="ns"))  # no raise == pass


class _FakeDaprClient:
    def __init__(self) -> None:
        self.published: list[dict[str, str]] = []

    async def publish_event(
        self, *, pubsub_name: str, topic_name: str, data: str, data_content_type: str
    ) -> None:
        self.published.append({"pubsub": pubsub_name, "topic": topic_name, "data": data})


def test_dapr_emitter_publishes_to_configured_pubsub_and_topic() -> None:
    client = _FakeDaprClient()
    emitter = DaprMaintenanceEmitter(
        cast(Any, client),
        "lineage-pubsub",
        "lineage.events.v1",
        job_namespace="compaction",
        timeout_seconds=5.0,
    )
    asyncio.run(emitter.emit_maintenance(table_id="ns$a", namespace="ns"))
    assert len(client.published) == 1
    assert client.published[0]["pubsub"] == "lineage-pubsub"
    assert client.published[0]["topic"] == "lineage.events.v1"
    payload = json.loads(client.published[0]["data"])
    assert payload["outputs"][0]["name"] == "ns$a"
    assert payload["run"]["facets"]["lance"]["operation"] == COMPACTION


def test_dapr_emitter_best_effort_swallows_publish_failure() -> None:
    # A sidecar/broker outage must NEVER fail a maintenance sweep — the publish is best-effort.
    class _BoomClient:
        async def publish_event(self, **_kw: Any) -> None:
            raise RuntimeError("sidecar down")

    emitter = DaprMaintenanceEmitter(
        cast(Any, _BoomClient()), "p", "t", job_namespace="compaction", timeout_seconds=5.0
    )
    asyncio.run(emitter.emit_maintenance(table_id="ns$a", namespace="ns"))  # no raise == pass
