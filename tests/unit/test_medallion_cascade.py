"""End-to-end test of the fake-Ray medallion CASCADE (#25) — raw → bronze → silver → gold, in-process.

This is the regression guard for "the event-driven loop produces real DATA + a correct lineage CHAIN".
It runs the producer + all three stage movers in sequence with the fake-Ray compute ON, against a temp
directory (real Lance, no S3/Dapr/AGE), capturing every emitted OpenLineage event, and asserts BOTH halves:

* **Data** — each stage's Lance dataset really exists, the original rows flow all the way to gold, and each
  hop is stamped with its stage; the lineage carries the real (advancing) Lance versions.
* **Lineage** — the captured events parse as the lineage service's ``RunEvent`` and form the
  ``raw → bronze → silver → gold`` ``DERIVED_FROM`` chain (each hop's input is the previous hop's output),
  i.e. the exact graph the lineage consumer would ingest.

The Dapr pub/sub fan-out + AGE ingest are exercised by the gated live e2e
(``tests/e2e/test_medallion_e2e.py``); here we prove the compute + lineage contract the whole cascade
rests on, runnably and deterministically.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import lance
from dapr.aio.clients import DaprClient
from lineage.models import Dataset, RunEvent
from medallion.core.config import MedallionSettings
from medallion.services.produce import produce
from medallion.services.transform import handle_stage


class _FakeDapr:
    """Captures every published event across the whole cascade (lineage emits + stage triggers)."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish_event(
        self, *, pubsub_name: str, topic_name: str, data: str, data_content_type: str
    ) -> None:
        self.published.append({"topic": topic_name, "data": json.loads(data)})


# The medallion DAG as (operation, from_ns, from_ds, to_ns, to_ds) — the same shape the chart wires per mover.
_HOPS = [
    ("ingest_events", "raw", "raw_events", "bronze", "bronze$events"),
    ("embed", "bronze", "bronze$events", "silver", "silver$features"),
    ("aggregate", "silver", "silver$features", "gold", "gold$catalog"),
]


def test_cascade_produces_real_data_and_a_correct_lineage_chain(tmp_path: Any) -> None:
    uris = {ns: str(tmp_path / ns) for ns in ("raw", "bronze", "silver", "gold")}
    dapr = _FakeDapr()

    # Head of the pipeline: lance-ray seeds raw_events (real Lance write).
    producer = MedallionSettings.model_validate(
        {"compute_enabled": True, "raw_uri": uris["raw"], "raw_namespace": "raw", "raw_dataset": "raw_events"}
    )
    asyncio.run(produce(cast(DaprClient, dapr), producer))
    raw_rows = lance.dataset(uris["raw"]).to_table().num_rows
    assert raw_rows > 0

    # The 3 movers, each reading its upstream Lance dataset and writing the downstream one.
    for op, from_ns, from_ds, to_ns, to_ds in _HOPS:
        settings = MedallionSettings.model_validate(
            {
                "compute_enabled": True,
                "from_uri": uris[from_ns],
                "to_uri": uris[to_ns],
                "from_namespace": from_ns,
                "from_dataset": from_ds,
                "to_namespace": to_ns,
                "to_dataset": to_ds,
                "operation": op,
                "pub_topic": "" if to_ns == "gold" else f"medallion.{to_ns}",
            }
        )
        result = asyncio.run(handle_stage(cast(DaprClient, dapr), settings, {"data": {"token": "tok"}}))
        assert result == {"status": "SUCCESS"}

    # --- Data: the original rows flowed all the way to gold, stamped at each stage. ---
    gold = lance.dataset(uris["gold"]).to_table()
    assert gold.num_rows == raw_rows  # no rows lost across the cascade
    assert set(gold.column("stage").to_pylist()) == {"gold"}

    # --- Lineage: the emitted events form the raw → bronze → silver → gold DERIVED_FROM chain. ---
    events = [
        RunEvent.model_validate(p["data"]) for p in dapr.published if p["topic"] == producer.lineage_topic
    ]
    by_output = {e.outputs[0].name: e for e in events}
    assert set(by_output) == {"raw_events", "bronze$events", "silver$features", "gold$catalog"}
    assert by_output["raw_events"].inputs == []  # raw is the source — no upstream
    assert by_output["bronze$events"].inputs[0].name == "raw_events"
    assert by_output["silver$features"].inputs[0].name == "bronze$events"
    assert by_output["gold$catalog"].inputs[0].name == "silver$features"
    # Every successful hop carries the real Lance version on its output (the WROTE edge the graph records).
    for name, ns in (("bronze$events", "bronze"), ("silver$features", "silver"), ("gold$catalog", "gold")):
        assert by_output[name].output_version(name) == str(lance.dataset(uris[ns]).version)


def test_source_rowid_traces_every_derived_row_back_to_its_exact_raw_source_row(tmp_path: Any) -> None:
    """#38a ROOT PROVENANCE: every bronze/silver/gold row carries ``source_rowid`` = the stable ``_rowid`` of
    the RAW row it descends from, so a gold row names its exact source in ONE join — not a hop-by-hop walk.

    Minted at the head (bronze ← the raw row's reserved ``_rowid`` metacolumn) and CARRIED UNCHANGED across
    silver and gold (NOT re-set to each parent's ``_rowid``). The columnLineage edge tells the two apart: the
    head declares ``source_rowid ← raw_events._rowid``, every carried stage ``source_rowid ← source_rowid``.
    """
    uris = {ns: str(tmp_path / ns) for ns in ("raw", "bronze", "silver", "gold")}
    dapr = _FakeDapr()
    producer = MedallionSettings.model_validate(
        {"compute_enabled": True, "raw_uri": uris["raw"], "raw_namespace": "raw", "raw_dataset": "raw_events"}
    )
    asyncio.run(produce(cast(DaprClient, dapr), producer))

    # The raw row identities the whole cascade must be able to name — captured AT seed time (id → _rowid),
    # because _rowid advances on any later overwrite, so only a snapshot taken now is join-valid.
    raw_tbl = lance.dataset(uris["raw"]).to_table(with_row_id=True)
    root_rowid_by_id = dict(
        zip(raw_tbl.column("id").to_pylist(), raw_tbl.column("_rowid").to_pylist(), strict=True)
    )
    assert "source_rowid" not in raw_tbl.column_names  # raw IS the source — it carries none of its own

    for op, from_ns, from_ds, to_ns, to_ds in _HOPS:
        settings = MedallionSettings.model_validate(
            {
                "compute_enabled": True,
                "from_uri": uris[from_ns],
                "to_uri": uris[to_ns],
                "from_namespace": from_ns,
                "from_dataset": from_ds,
                "to_namespace": to_ns,
                "to_dataset": to_ds,
                "operation": op,
                "pub_topic": "" if to_ns == "gold" else f"medallion.{to_ns}",
            }
        )
        assert asyncio.run(handle_stage(cast(DaprClient, dapr), settings, {"data": {"token": "t"}})) == {
            "status": "SUCCESS"
        }

    # DATA: every stage names the SAME root raw row per id — bronze, silver AND gold, unchanged.
    for ns in ("bronze", "silver", "gold"):
        tbl = lance.dataset(uris[ns]).to_table()
        assert "source_rowid" in tbl.column_names, f"{ns} dropped row-level provenance"
        by_id = dict(zip(tbl.column("id").to_pylist(), tbl.column("source_rowid").to_pylist(), strict=True))
        assert by_id == root_rowid_by_id, f"{ns} lost or rewrote the root source_rowid"

    # LINEAGE: the head MINTS the edge from the reserved _rowid; a carried stage declares plain IDENTITY.
    pubs = {
        p["data"]["outputs"][0]["name"]: p["data"]
        for p in dapr.published
        if p["topic"] == producer.lineage_topic
    }

    def _srid_edge(output_name: str) -> tuple[str, str, str]:
        out = Dataset.model_validate(pubs[output_name]["outputs"][0])
        edge = next(e for e in out.column_edges if e["out_field"] == "source_rowid")
        return edge["name"], edge["field"], edge["subtype"]

    assert _srid_edge("bronze$events") == ("raw_events", "_rowid", "IDENTITY")  # minted at the head
    assert _srid_edge("gold$catalog") == ("silver$features", "source_rowid", "IDENTITY")  # carried forward
