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
            downstream = await repo.downstream("raw_images")
            producers = await repo.producers("silver$features")
            graph = await repo.graph("silver$features")
            return upstream, downstream, producers, graph
        finally:
            await pool.close()

    upstream, downstream, producers, graph = asyncio.run(run())

    # gold derives (transitively) from silver, bronze and the raw sources.
    assert {"silver$features", "bronze$images", "raw_images"} <= {d.name for d in upstream.related}
    # raw_images flows downstream into bronze/silver/gold.
    assert {"bronze$images", "silver$features", "gold$catalog"} <= {d.name for d in downstream.related}
    # silver was produced by the lance-ray embed run, authored by data_eng.
    assert producers.producers and producers.producers[0].author == "data_eng"
    # the graph around silver spans the whole connected medallion DAG.
    node_ids = {n.id for n in graph.nodes}
    assert {"raw_images", "raw_images_batch2", "bronze$images", "silver$features", "gold$catalog"} <= node_ids
    # silver derives from bronze (a DERIVED_FROM edge), and gold derives from silver.
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("silver$features", "bronze$images") in edges
    assert ("gold$catalog", "silver$features") in edges
