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
_SAMPLE = Path(__file__).resolve().parent.parent.parent / "lineage" / "sample_events.json"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def dsn() -> str:
    if not DSN:
        pytest.skip("set LINEAGE_DATABASE_URL (a live Apache AGE Postgres) to run the lineage e2e")
    return DSN


def test_medallion_ingest_and_lineage_queries(dsn: str) -> None:
    from lineage.age import make_pool
    from lineage.models import RunEvent
    from lineage.repository import LineageRepository
    from lineage.schemas import LineageGraph, Neighbors, Producers

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
    # silver was written twice — v1 (embed) then v2 (caption), both by data_eng (the refinement passes).
    assert {p.author for p in producers.producers} == {"data_eng"}
    assert {p.dataset_version for p in producers.producers} >= {"1", "2"}
    # the graph around silver spans the connected medallion DAG.
    node_ids = {n.id for n in graph.nodes}
    assert {"raw_events", "bronze$events", "silver$features", "gold$catalog"} <= node_ids
    # silver derives from bronze, gold from silver; the in-place refine is NOT a self-derivation.
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("silver$features", "bronze$events") in edges
    assert ("gold$catalog", "silver$features") in edges
    assert ("silver$features", "silver$features") not in edges
