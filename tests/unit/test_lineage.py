"""Unit tests for the lineage service's pure logic (no database).

Covers OpenLineage event parsing (camelCase aliases + author facet) and the AGE
SQL/result helpers — the parts we own, deterministic and infra-free.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from lineage.age import _parse, _sql
from lineage.models import RunEvent

_SAMPLE = Path(__file__).resolve().parent.parent.parent / "lineage" / "sample_events.json"


def test_run_event_parses_openlineage_camelcase() -> None:
    event = RunEvent.model_validate(
        {
            "eventType": "COMPLETE",
            "eventTime": "2026-06-20T09:00:00Z",
            "run": {"runId": "r1", "facets": {"author": {"name": "alice"}}},
            "job": {"namespace": "lance-jobs", "name": "ingest"},
            "inputs": [{"namespace": "source", "name": "raw_images"}],
            "outputs": [{"namespace": "bronze", "name": "bronze$images"}],
        }
    )
    assert event.event_type == "COMPLETE"
    assert event.run.run_id == "r1"
    assert event.author == "alice"
    assert event.inputs[0].name == "raw_images"
    assert event.outputs[0].name == "bronze$images"


def test_author_absent_is_none() -> None:
    event = RunEvent.model_validate(
        {
            "eventType": "START",
            "eventTime": "t",
            "run": {"runId": "r2"},
            "job": {"namespace": "j", "name": "n"},
        }
    )
    assert event.author is None


_JOBS = ["ingest_events", "embed_features", "embed_features", "caption_features", "aggregate_gold"]


def test_sample_events_all_valid() -> None:
    events = [RunEvent.model_validate(e) for e in json.loads(_SAMPLE.read_text())]
    assert [e.job.name for e in events] == _JOBS


def test_emitter_output_parses_in_service_model() -> None:
    """Events from the real OpenLineage client must round-trip into our Pydantic model."""
    from lineage.seed import events_as_dicts

    events = [RunEvent.model_validate(e) for e in events_as_dicts()]
    assert [e.job.name for e in events] == _JOBS
    assert events[0].author == "alice"  # custom AuthorRunFacet read through
    assert events[0].outputs[0].name == "bronze$events"
    # events[1] is the FAILED embed attempt, events[2] the successful retry.
    assert events[1].author == "data_eng" and events[1].is_failure
    assert events[2].author == "data_eng" and events[2].is_success


def test_silver_refinement_records_two_versions() -> None:
    """The two successful passes over silver produce versions 1 then 2 ('run against silver again')."""
    from lineage.seed import events_as_dicts

    events = [RunEvent.model_validate(e) for e in events_as_dicts()]
    # events[2] embed wrote silver v1; events[3] caption refined it in place -> v2.
    assert events[2].output_version("silver$features") == "1"
    assert events[3].output_version("silver$features") == "2"
    # the refine reads AND writes silver (in-place) — a version bump, not a new lineage edge.
    assert events[3].inputs[0].name == events[3].outputs[0].name == "silver$features"


def test_failed_run_exposes_producer_error_and_standard_dataset_facets() -> None:
    """The failed embed carries producer + errorMessage; outputs carry dataSource + tags facets."""
    from lineage.seed import events_as_dicts

    failed = RunEvent.model_validate(events_as_dicts()[1])
    assert failed.is_failure and not failed.is_success
    assert failed.producer and failed.producer.startswith("https://")
    assert failed.error_message and "OOM" in failed.error_message
    out = failed.outputs[0]
    assert out.name == "silver$features"
    assert out.source_uri == "s3://lakehouse/silver/features"  # standard dataSource facet
    assert "layer=silver" in out.tags  # standard tags facet


def test_author_falls_back_to_standard_ownership_facet() -> None:
    """With no custom author facet, the run author comes from the standard ownership job facet."""
    event = RunEvent.model_validate(
        {
            "eventType": "COMPLETE",
            "eventTime": "t",
            "run": {"runId": "r"},
            "job": {
                "namespace": "ray-jobs",
                "name": "j",
                "facets": {"ownership": {"owners": [{"name": "carol", "type": "user"}]}},
            },
        }
    )
    assert event.author == "carol"


def test_sql_inlines_validated_graph_and_adds_params_arg() -> None:
    with_params = _sql("lineage", "MATCH (d) RETURN d", with_params=True, columns=1).as_string()
    assert "cypher('lineage'" in with_params
    assert "$$ MATCH (d) RETURN d $$" in with_params  # AGE requires dollar-quoting
    assert "%s" in with_params  # params bind slot present
    no_params = _sql("lineage", "RETURN 1", with_params=False, columns=2).as_string()
    assert "%s" not in no_params  # omitted when there are no params
    assert '"c0" agtype, "c1" agtype' in no_params


def test_sql_rejects_non_identifier_graph() -> None:
    with pytest.raises(ValueError, match="invalid graph name"):
        _sql("lineage; DROP TABLE x", "RETURN 1", with_params=False, columns=1)


class _Tx:
    async def __aenter__(self) -> _Tx:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False


class _Conn:
    def transaction(self) -> _Tx:
        return _Tx()


class _PoolCM:
    async def __aenter__(self) -> _Conn:
        return _Conn()

    async def __aexit__(self, *_a: object) -> bool:
        return False


class _FakePool:
    """Just enough of an AsyncConnectionPool to exercise ingest_event without a database."""

    def connection(self) -> _PoolCM:
        return _PoolCM()


def _capture_ingest(monkeypatch: pytest.MonkeyPatch, event_index: int) -> list[tuple[str, dict[str, object]]]:
    """Ingest one seed event against a fake pool, capturing the Cypher calls it issues."""
    import lineage.repository as repo_mod
    from lineage.seed import events_as_dicts

    calls: list[tuple[str, dict[str, object]]] = []

    async def _capture(_conn: object, _graph: str, query: str, params: dict[str, object]) -> None:
        calls.append((query, params))

    monkeypatch.setattr(repo_mod, "run_cypher", _capture)
    repo = repo_mod.LineageRepository(cast(Any, _FakePool()), "g")
    asyncio.run(repo.ingest_event(RunEvent.model_validate(events_as_dicts()[event_index])))
    return calls


def test_ingest_records_version_and_skips_self_derived_from(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-place silver refinement records version=2 on WROTE and emits NO self-DERIVED_FROM."""
    calls = _capture_ingest(monkeypatch, 3)  # silver -> silver (add caption), v2

    wrote = [p for q, p in calls if "WROTE" in q]
    assert any(p.get("name") == "silver$features" and p.get("ver") == "2" for p in wrote)
    # in-place transform: read + write the same table, but NO self-DERIVED_FROM edge.
    assert [p for q, p in calls if "DERIVED_FROM" in q] == []
    # the standard dataSource + tags facets are persisted onto the dataset node.
    assert any("source_uri" in q for q, _ in calls)
    assert any("d.tags" in q for q, _ in calls)


def test_failed_run_records_error_but_no_version_or_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed run is recorded (run + error + WROTE) but asserts NO version and NO derivation."""
    calls = _capture_ingest(monkeypatch, 1)  # the FAILED embed attempt

    run_merges = [p for q, p in calls if "MERGE (r:Run" in q]
    assert run_merges and run_merges[0].get("err")  # errorMessage stored on the run
    wrote = [p for q, p in calls if "WROTE" in q]
    assert wrote and all(p.get("ver") == "" for p in wrote)  # attempt recorded, but no version
    # a failed run produced no data, so it must not assert lineage.
    assert [p for q, p in calls if "DERIVED_FROM" in q] == []


def test_parse_handles_scalars_vertices_and_null() -> None:
    assert _parse('"bronze$images"') == "bronze$images"
    assert _parse("3") == 3
    assert _parse(None) is None
    vertex = _parse('{"id":1,"label":"Dataset","properties":{"name":"x"}}::vertex')
    assert vertex["label"] == "Dataset"
    assert vertex["properties"]["name"] == "x"
