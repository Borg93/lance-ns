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


def test_sample_events_all_valid() -> None:
    events = [RunEvent.model_validate(e) for e in json.loads(_SAMPLE.read_text())]
    assert [e.job.name for e in events] == [
        "ingest_events",
        "embed_features",
        "caption_features",
        "aggregate_gold",
    ]


def test_emitter_output_parses_in_service_model() -> None:
    """Events from the real OpenLineage client must round-trip into our Pydantic model."""
    from lineage.seed import events_as_dicts

    events = [RunEvent.model_validate(e) for e in events_as_dicts()]
    assert [e.job.name for e in events] == [
        "ingest_events",
        "embed_features",
        "caption_features",
        "aggregate_gold",
    ]
    assert events[0].author == "alice"  # custom AuthorRunFacet read through
    assert events[0].outputs[0].name == "bronze$events"
    assert events[1].author == "data_eng"


def test_silver_refinement_records_two_versions() -> None:
    """The two passes over silver produce versions 1 then 2 (the 'run against silver again')."""
    from lineage.seed import events_as_dicts

    events = [RunEvent.model_validate(e) for e in events_as_dicts()]
    # embed_features wrote silver v1; caption_features refined it in place -> v2.
    assert events[1].output_version("silver$features") == "1"
    assert events[2].output_version("silver$features") == "2"
    # the second pass reads AND writes silver (in-place) — an in-place refinement, not a new lineage edge.
    assert events[2].inputs[0].name == events[2].outputs[0].name == "silver$features"


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


def test_ingest_records_version_and_skips_self_derived_from(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-place silver refinement records version=2 on WROTE and emits NO self-DERIVED_FROM."""
    import lineage.repository as repo_mod
    from lineage.seed import events_as_dicts

    calls: list[tuple[str, dict[str, object]]] = []

    async def _capture(_conn: object, _graph: str, query: str, params: dict[str, object]) -> None:
        calls.append((query, params))

    monkeypatch.setattr(repo_mod, "run_cypher", _capture)
    repo = repo_mod.LineageRepository(cast(Any, _FakePool()), "g")
    refine = RunEvent.model_validate(events_as_dicts()[2])  # silver -> silver (add caption), v2
    asyncio.run(repo.ingest_event(refine))

    wrote = [p for q, p in calls if "WROTE" in q]
    assert any(p.get("name") == "silver$features" and p.get("ver") == "2" for p in wrote)
    # in-place transform: read + write the same table, but NO self-DERIVED_FROM edge.
    assert [p for q, p in calls if "DERIVED_FROM" in q] == []


def test_parse_handles_scalars_vertices_and_null() -> None:
    assert _parse('"bronze$images"') == "bronze$images"
    assert _parse("3") == 3
    assert _parse(None) is None
    vertex = _parse('{"id":1,"label":"Dataset","properties":{"name":"x"}}::vertex')
    assert vertex["label"] == "Dataset"
    assert vertex["properties"]["name"] == "x"
