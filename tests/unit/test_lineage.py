"""Unit tests for the lineage service's pure logic (no database).

Covers OpenLineage event parsing (camelCase aliases + author facet) and the AGE
SQL/result helpers — the parts we own, deterministic and infra-free.
"""

from __future__ import annotations

import json
from pathlib import Path

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
        "ingest_images",
        "lanceray_append_images",
        "lanceray_embed",
        "aggregate_gold",
    ]


def test_emitter_output_parses_in_service_model() -> None:
    """Events from the real OpenLineage client must round-trip into our Pydantic model."""
    from lineage.seed import events_as_dicts

    events = [RunEvent.model_validate(e) for e in events_as_dicts()]
    assert [e.job.name for e in events] == [
        "ingest_images",
        "lanceray_append_images",
        "lanceray_embed",
        "aggregate_gold",
    ]
    assert events[0].author == "alice"  # custom AuthorRunFacet read through
    assert events[0].outputs[0].name == "bronze$images"
    assert events[2].author == "data_eng"


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


def test_parse_handles_scalars_vertices_and_null() -> None:
    assert _parse('"bronze$images"') == "bronze$images"
    assert _parse("3") == 3
    assert _parse(None) is None
    vertex = _parse('{"id":1,"label":"Dataset","properties":{"name":"x"}}::vertex')
    assert vertex["label"] == "Dataset"
    assert vertex["properties"]["name"] == "x"
