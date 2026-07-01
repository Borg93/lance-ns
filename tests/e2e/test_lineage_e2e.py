"""Lineage ingest + query end-to-end against a live Apache AGE database.

Skipped unless ``LINEAGE_DATABASE_URL`` points at a running AGE Postgres, e.g.:

    docker compose -f .docker/docker-compose.yml -f .docker/docker-compose.lineage.yml up -d lineage-postgres
    LINEAGE_DATABASE_URL=postgresql://lineage:lineage@localhost:5433/lineage \
        uv run pytest tests/e2e/test_lineage_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

DSN = os.environ.get("LINEAGE_DATABASE_URL", "")
_SAMPLE = Path(__file__).resolve().parents[2] / "services" / "lineage" / "sample_events.json"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def dsn() -> str:
    if not DSN:
        pytest.skip("set LINEAGE_DATABASE_URL (a live Apache AGE Postgres) to run the lineage e2e")
    return DSN


def test_medallion_ingest_and_lineage_queries(dsn: str) -> None:
    from lineage.core.age import make_pool
    from lineage.models import RunEvent
    from lineage.schemas import LineageGraph, Neighbors, Producers
    from lineage.services.repository import LineageRepository

    events = [RunEvent.model_validate(e) for e in json.loads(_SAMPLE.read_text())]

    async def run() -> tuple[Neighbors, Neighbors, Producers, LineageGraph]:
        pool = make_pool(dsn)
        await pool.open()
        try:
            repo = LineageRepository(pool, "lineage")
            for event in events:
                await repo.ingest_event(event)
            upstream = await repo.upstream("gold$catalog")
            downstream = await repo.downstream("raw_events")
            producers = await repo.producers("silver$features")
            graph = await repo.graph("silver$features")
            return upstream, downstream, producers, graph
        finally:
            await pool.close()

    upstream, downstream, producers, graph = asyncio.run(run())

    # gold derives (transitively) from silver, bronze and the raw source.
    assert {"silver$features", "bronze$events", "raw_events"} <= {d.name for d in upstream.related}
    # raw_events flows downstream into bronze/silver/gold.
    assert {"bronze$events", "silver$features", "gold$catalog"} <= {d.name for d in downstream.related}
    # silver was written by data_eng across all attempts (failed embed, embed v1, caption v2).
    assert {p.author for p in producers.producers} == {"data_eng"}
    assert {p.dataset_version for p in producers.producers} >= {"1", "2"}
    # the failed embed attempt is recorded too: a FAIL run with an error and no produced version.
    failed = [p for p in producers.producers if p.event_type and "FAIL" in p.event_type.upper()]
    assert failed and failed[0].error_message and "OOM" in failed[0].error_message
    assert failed[0].dataset_version is None
    # the graph around silver spans the connected medallion DAG, with storage + tags on each node.
    node_ids = {n.id for n in graph.nodes}
    assert {"raw_events", "bronze$events", "silver$features", "gold$catalog"} <= node_ids
    silver_node = next(n for n in graph.nodes if n.id == "silver$features")
    assert silver_node.source_uri == "s3://lakehouse/silver/features"
    assert "layer=silver" in silver_node.tags
    # silver derives from bronze, gold from silver; the in-place refine is NOT a self-derivation.
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("silver$features", "bronze$events") in edges
    assert ("gold$catalog", "silver$features") in edges
    assert ("silver$features", "silver$features") not in edges


def test_discovery_lists_against_age(dsn: str) -> None:
    """GOAL 4 A1/A2: the browse lists run their REAL Cypher against AGE (not a mocked ``run_cypher``).

    Ingest the medallion sample, then exercise ``list_datasets`` (all + namespace / tag filters) and
    ``list_jobs`` (the job -> written-datasets fold) — the discovery reads a normal ``uv run pytest``
    otherwise never executes against a database.
    """
    from lineage.core.age import make_pool
    from lineage.models import RunEvent
    from lineage.services.repository import LineageRepository

    events = [RunEvent.model_validate(e) for e in json.loads(_SAMPLE.read_text())]

    async def run() -> tuple[list, list, list, list]:
        pool = make_pool(dsn)
        await pool.open()
        try:
            repo = LineageRepository(pool, "lineage")
            for event in events:
                await repo.ingest_event(event)
            all_ds = await repo.list_datasets()
            silver = await repo.list_datasets(namespace="silver")
            tagged = await repo.list_datasets(tag="layer=silver")
            jobs = await repo.list_jobs()
            return all_ds, silver, tagged, jobs
        finally:
            await pool.close()

    all_ds, silver, tagged, jobs = asyncio.run(run())

    # /datasets — every medallion dataset is listed, name-sorted, with its namespace + tags carried.
    names = [d.name for d in all_ds]
    assert {"raw_events", "bronze$events", "silver$features", "gold$catalog"} <= set(names)
    assert names == sorted(names)
    # ?namespace= filter — only silver-namespace datasets (silver$features lives there).
    assert silver and all(d.namespace == "silver" for d in silver)
    assert "silver$features" in {d.name for d in silver}
    # ?tag= filter — exact tag membership picks up the silver dataset.
    assert "silver$features" in {d.name for d in tagged}
    assert all("layer=silver" in d.tags for d in tagged)
    # /jobs — a job's WROTE edges are folded into its output set; some job wrote silver$features.
    assert jobs and any("silver$features" in j.outputs for j in jobs)


def test_reconcile_backfills_a_dropped_write(dsn: str, tmp_path: Path) -> None:
    """B4: a write whose lineage event was LOST (storage ahead of the graph) is back-filled by reconcile.

    Simulates the outbox gap end-to-end against real AGE + real Lance: record a write at v1, land a second
    version on disk WITHOUT its lineage event, then reconcile — the graph must catch up to the on-disk v2.
    """
    import lance
    import pyarrow as pa
    from lineage.core.age import make_pool, run_cypher
    from lineage.core.reconcile import read_storage_version, reconcile_all
    from lineage.models import RunEvent
    from lineage.schemas import ReconcileState
    from lineage.services.repository import LineageRepository

    uri = str(tmp_path / "recon.lance")
    lance.write_dataset(pa.table({"id": [1]}), uri)  # storage v1
    event = RunEvent.model_validate(
        {
            "eventType": "COMPLETE",
            "eventTime": "2026-07-01T00:00:00Z",
            "run": {"runId": "recon-w1"},
            "job": {"namespace": "lance-medallion", "name": "recon_ingest"},
            "inputs": [],
            "outputs": [
                {
                    "namespace": "recon",
                    "name": "recon$t",
                    "facets": {"dataSource": {"uri": uri}, "version": {"datasetVersion": "1"}},
                }
            ],
        }
    )
    # A SECOND write lands on disk but its lineage event is DROPPED (the outbox gap): storage=2, graph=1.
    lance.write_dataset(pa.table({"id": [2]}), uri, mode="append")

    async def read_only_recon(u: str) -> int | None:
        return read_storage_version(u, {}) if u == uri else None  # skip other datasets' (s3) reads

    async def run() -> tuple[int | None, ReconcileState, int | None]:
        pool = make_pool(dsn)
        await pool.open()
        try:
            repo = LineageRepository(pool, "lineage")
            # The AGE graph persists across runs — clear this test's dataset + runs so it starts clean
            # (else a prior back-fill leaves recon$t at v2 and the "graph behind storage" premise breaks).
            async with pool.connection() as conn:
                await run_cypher(conn, "lineage", "MATCH (d:Dataset {name:'recon$t'}) DETACH DELETE d")
                await run_cypher(
                    conn,
                    "lineage",
                    "MATCH (r:Run) WHERE r.run_id IN ['recon-w1', 'reconcile-recon$t-v2'] DETACH DELETE r",
                )
            await repo.ingest_event(event)
            before = await repo.latest_write_version("recon$t")
            statuses = await reconcile_all(repo, read_only_recon, backfill=True)
            after = await repo.latest_write_version("recon$t")
            recon = next(s for s in statuses if s.dataset == "recon$t")
            return before, recon.status, after
        finally:
            await pool.close()

    before, status, after = asyncio.run(run())
    assert before == 1  # the graph recorded v1 from the event
    assert status == ReconcileState.STORAGE_AHEAD  # storage v2 > graph v1 — the dropped write
    assert after == 2  # reconcile back-filled the real on-disk version


def test_medallion_column_lineage(dsn: str) -> None:
    """#24: field-to-field lineage ingested into real AGE then traversed (the high-risk cypher path).

    Exercises the bits unit tests can't: the ``DERIVED_FROM_COLUMN*1..`` transitive walk across datasets
    AND within one (the same-dataset caption←embedding edge), the typed HAS_COLUMN inventory, and the
    bool/scalar edge props round-tripping through AGE.
    """
    from lineage.core.age import make_pool
    from lineage.models import RunEvent
    from lineage.schemas import ColumnGraph, ColumnNeighbors
    from lineage.services.repository import LineageRepository

    events = [RunEvent.model_validate(e) for e in json.loads(_SAMPLE.read_text())]

    async def run() -> tuple[ColumnNeighbors, ColumnNeighbors, ColumnGraph]:
        pool = make_pool(dsn)
        await pool.open()
        try:
            repo = LineageRepository(pool, "lineage")
            for event in events:
                await repo.ingest_event(event)
            up = await repo.column_upstream("gold$catalog", "caption")
            down = await repo.column_downstream("bronze$events", "payload")
            cg = await repo.dataset_column_graph("silver$features")
            return up, down, cg
        finally:
            await pool.close()

    up, down, cg = asyncio.run(run())

    # gold.caption traces back through silver.caption -> silver.embedding -> bronze.payload
    # (a cross-dataset AND a same-dataset column hop in one transitive walk).
    up_cols = {(c.dataset, c.field) for c in up.related}
    assert {
        ("silver$features", "caption"),
        ("silver$features", "embedding"),
        ("bronze$events", "payload"),
    } <= up_cols
    # bronze.payload flows downstream into silver.embedding and onward to gold.caption.
    down_cols = {(c.dataset, c.field) for c in down.related}
    assert {("silver$features", "embedding"), ("gold$catalog", "caption")} <= down_cols
    # the silver column graph carries its full typed inventory + the in-place caption<-embedding edge.
    typed = {c.field: c.type for c in cg.columns if c.dataset == "silver$features"}
    assert {"id", "payload_src", "embedding", "caption"} <= set(typed)
    assert typed["embedding"] == "array<float>"  # the Arrow type seeded from the schema facet
    same_ds = {
        (e.source_field, e.target_field)
        for e in cg.edges
        if e.source_dataset == "silver$features" and e.target_dataset == "silver$features"
    }
    assert ("embedding", "caption") in same_ds  # the in-place-refinement column edge
    # the embed transformation kind rode the edge as a scalar prop.
    emb = next(e for e in cg.edges if e.target_dataset == "silver$features" and e.target_field == "embedding")
    assert emb.transformation_subtype == "TRANSFORMATION"
