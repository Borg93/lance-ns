"""Unit tests for the event-driven medallion movers + lance-ray producer.

Infra-free: no sidecar, no broker. A fake Dapr client records publishes; we pin the contract each
service must honor — the mover emits the transform's lineage (inputs→outputs) AND the next stage's
trigger, returns SUCCESS (RETRY on a publish outage), and the producer emits raw + the first trigger.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

import medallion.mover as mover
import medallion.producer as producer
from medallion.config import MedallionSettings
from medallion.events import build_run_event


class _FakeDapr:
    """Records publish_event calls; optionally fails to exercise the RETRY path."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def publish_event(self, *, pubsub_name: str, topic_name: str, data: str, **_: Any) -> None:
        if self._fail:
            raise RuntimeError("sidecar down")
        self.calls.append({"pubsub": pubsub_name, "topic": topic_name, "data": json.loads(data)})


_BRONZE_TO_SILVER = MedallionSettings.model_validate(
    {
        "from_namespace": "bronze",
        "from_dataset": "bronze$events",
        "to_namespace": "silver",
        "to_dataset": "silver$features",
        "operation": "embed_features",
        "author": "data_eng",
        "sub_topic": "medallion.bronze",
        "pub_topic": "medallion.silver",
    }
)


def test_build_run_event_records_the_transform_edge() -> None:
    event = build_run_event(
        operation="embed_features",
        author="data_eng",
        job_namespace="lance-medallion",
        inputs=[("bronze", "bronze$events")],
        output_namespace="silver",
        output_name="silver$features",
        version=2,
        run_id="embed-1",
    )
    assert event["inputs"][0]["name"] == "bronze$events"
    assert event["outputs"][0]["name"] == "silver$features"
    assert event["outputs"][0]["facets"]["version"]["datasetVersion"] == "2"
    assert event["run"]["facets"]["author"]["sub"] == "data_eng"
    assert event["job"]["name"] == "embed_features"


def test_mover_emits_lineage_then_triggers_next_stage() -> None:
    dapr = _FakeDapr()
    event = {"data": {"token": "abc123", "dataset": "bronze$events", "namespace": "bronze"}}

    status = asyncio.run(mover.handle_stage(cast(Any, dapr), _BRONZE_TO_SILVER, event))

    assert status == {"status": "SUCCESS"}
    assert len(dapr.calls) == 2  # the lineage event, then the next-stage trigger
    lineage, trigger = dapr.calls
    assert lineage["topic"] == "lineage.events.v1"
    assert lineage["data"]["inputs"][0]["name"] == "bronze$events"
    assert lineage["data"]["outputs"][0]["name"] == "silver$features"
    assert lineage["data"]["run"]["runId"] == "embed_features-abc123"  # run correlated to the token
    assert trigger["topic"] == "medallion.silver"
    assert trigger["data"] == {"token": "abc123", "dataset": "silver$features", "namespace": "silver"}


def test_terminal_mover_emits_lineage_but_no_next_trigger() -> None:
    terminal = _BRONZE_TO_SILVER.model_copy(update={"pub_topic": ""})  # gold: no downstream
    dapr = _FakeDapr()

    status = asyncio.run(mover.handle_stage(cast(Any, dapr), terminal, {"data": {"token": "t"}}))

    assert status == {"status": "SUCCESS"}
    assert len(dapr.calls) == 1 and dapr.calls[0]["topic"] == "lineage.events.v1"


def test_mover_retries_on_publish_failure() -> None:
    status = asyncio.run(
        mover.handle_stage(cast(Any, _FakeDapr(fail=True)), _BRONZE_TO_SILVER, {"data": {"token": "t"}})
    )
    assert status == {"status": "RETRY"}


def test_producer_emits_raw_then_first_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(producer, "get_settings", lambda: MedallionSettings())  # defaults: raw_events
    dapr = _FakeDapr()
    producer.app.state.dapr = dapr

    result = asyncio.run(producer.produce())

    assert result["status"] == "produced"
    assert len(dapr.calls) == 2
    raw_lineage, trigger = dapr.calls
    assert raw_lineage["topic"] == "lineage.events.v1"
    assert raw_lineage["data"]["outputs"][0]["name"] == "raw_events"
    assert raw_lineage["data"]["inputs"] == []  # raw is the source — no upstream
    assert trigger["topic"] == "medallion.raw"
    assert trigger["data"]["dataset"] == "raw_events"
