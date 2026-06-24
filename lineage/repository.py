"""Data-access layer for the lineage graph — all openCypher lives here.

The repository owns the two halves of the AGE graph: the **write** path (ingest an
OpenLineage run event → MERGE Run/Job/Dataset nodes + edges) and the **read** path
(traverse provenance / impact / producers). Endpoints depend on this class and never
see raw Cypher — per the layered architecture (handlers → repository → AGE).

Graph shape::

    (:Job {namespace, name})
    (:Run {run_id, author, event_type, event_time})
    (:Dataset {name, namespace})              # name = catalog table id
    (:User {name})                            # an OIDC sub (the verified principal)
    (:Run)-[:OF_JOB]->(:Job)
    (:Run)-[:READ]->(:Dataset)                # inputs
    (:Run)-[:WROTE]->(:Dataset)               # outputs
    (:Dataset)-[:DERIVED_FROM]->(:Dataset)    # output <- input (dataset lineage)
    (:User)-[:CREATED]->(:Dataset)            # who created the table (catalog create event)

Datasets are MERGEd on ``{name}`` only (then ``namespace`` is SET) so a dataset
referenced by several runs is never duplicated.
"""

from __future__ import annotations

from typing import Final

from psycopg_pool import AsyncConnectionPool

from lineage.age import fetch, run_cypher
from lineage.models import Dataset, RunEvent
from lineage.schemas import (
    Creator,
    DatasetRef,
    GraphEdge,
    GraphNode,
    LineageGraph,
    Neighbors,
    ProducerInfo,
    Producers,
)

# Must match app.core.lineage_emit.CREATE_TABLE — the OpenLineage ``lance`` facet operation the
# catalog emits on create, which keys the (:User)-[:CREATED]->(:Dataset) edge below (wire contract).
_CREATE_TABLE_OP: Final = "create_table"

_MERGE_JOB: Final = "MERGE (j:Job {namespace:$ns, name:$nm}) RETURN 1"
_MERGE_RUN: Final = (
    "MERGE (r:Run {run_id:$rid}) SET r.event_type=$et, r.event_time=$tm, r.author=$au RETURN 1"
)
_LINK_RUN_JOB: Final = (
    "MATCH (r:Run {run_id:$rid}), (j:Job {namespace:$ns, name:$nm}) MERGE (r)-[:OF_JOB]->(j) RETURN 1"
)
_MERGE_DATASET: Final = "MERGE (d:Dataset {name:$name}) SET d.namespace=$ns RETURN 1"
_LINK_READ: Final = "MATCH (r:Run {run_id:$rid}), (d:Dataset {name:$name}) MERGE (r)-[:READ]->(d) RETURN 1"
_LINK_WROTE: Final = "MATCH (r:Run {run_id:$rid}), (d:Dataset {name:$name}) MERGE (r)-[:WROTE]->(d) RETURN 1"
_DERIVED_FROM: Final = (
    "MATCH (o:Dataset {name:$on}), (i:Dataset {name:$inp}) MERGE (o)-[:DERIVED_FROM]->(i) RETURN 1"
)

_UPSTREAM: Final = (
    "MATCH (d:Dataset {name:$name})-[:DERIVED_FROM*1..]->(u:Dataset) RETURN DISTINCT u.name, u.namespace"
)
_DOWNSTREAM: Final = (
    "MATCH (d:Dataset {name:$name})<-[:DERIVED_FROM*1..]-(x:Dataset) RETURN DISTINCT x.name, x.namespace"
)
_PRODUCERS: Final = (
    "MATCH (r:Run)-[:WROTE]->(d:Dataset {name:$name}) RETURN r.run_id, r.author, r.event_time, r.event_type"
)
_MERGE_USER: Final = "MERGE (u:User {name:$name}) RETURN 1"
# Latest-create-wins: the CREATED edge carries the create event_time so creator() is deterministic
# even when a table name is dropped+recreated by a different principal (the most recent create is
# authoritative). A re-create updates this principal; drop-lineage GC is future work.
_LINK_CREATED: Final = (
    "MATCH (u:User {name:$name}), (d:Dataset {name:$ds}) "
    "MERGE (u)-[c:CREATED]->(d) SET c.created_at=$tm RETURN 1"
)
_CREATOR: Final = (
    "MATCH (u:User)-[c:CREATED]->(d:Dataset {name:$name}) RETURN u.name ORDER BY c.created_at DESC LIMIT 1"
)

# AGE rejects zero-length variable paths (``*0..``), so the connected node set is
# assembled from the upstream + downstream traversals (``*1..``) plus the root itself,
# and edges are filtered to that name set.
_DATASET_NS: Final = "MATCH (d:Dataset {name:$name}) RETURN d.namespace"
_GRAPH_EDGES: Final = (
    "MATCH (a:Dataset)-[:DERIVED_FROM]->(b:Dataset) "
    "WHERE a.name IN $names AND b.name IN $names RETURN DISTINCT a.name, b.name"
)


class LineageRepository:
    """Reads and writes the OpenLineage graph in one Apache AGE database."""

    def __init__(self, pool: AsyncConnectionPool, graph: str) -> None:
        self._pool = pool
        self._graph = graph

    async def ingest_event(self, event: RunEvent) -> None:
        """Upsert the run, its job, its datasets, and their edges in one transaction."""
        async with self._pool.connection() as conn, conn.transaction():
            await run_cypher(
                conn,
                self._graph,
                _MERGE_JOB,
                {"ns": event.job.namespace, "nm": event.job.name},
            )
            await run_cypher(
                conn,
                self._graph,
                _MERGE_RUN,
                {
                    "rid": event.run.run_id,
                    "et": event.event_type,
                    "tm": event.event_time,
                    "au": event.author or "",
                },
            )
            await run_cypher(
                conn,
                self._graph,
                _LINK_RUN_JOB,
                {"rid": event.run.run_id, "ns": event.job.namespace, "nm": event.job.name},
            )
            for ds in event.inputs:
                await self._merge_dataset(conn, ds)
                await run_cypher(
                    conn,
                    self._graph,
                    _LINK_READ,
                    {"rid": event.run.run_id, "name": ds.name},
                )
            for ds in event.outputs:
                await self._merge_dataset(conn, ds)
                await run_cypher(
                    conn,
                    self._graph,
                    _LINK_WROTE,
                    {"rid": event.run.run_id, "name": ds.name},
                )
            for out in event.outputs:
                for inp in event.inputs:
                    await run_cypher(
                        conn,
                        self._graph,
                        _DERIVED_FROM,
                        {"on": out.name, "inp": inp.name},
                    )
            # A catalog "create_table" event carries the verified author → record who created the
            # table as a first-class (:User)-[:CREATED]->(:Dataset) edge (the who-created answer).
            if event.operation == _CREATE_TABLE_OP and event.author:
                await run_cypher(conn, self._graph, _MERGE_USER, {"name": event.author})
                for ds in event.outputs:
                    await run_cypher(
                        conn,
                        self._graph,
                        _LINK_CREATED,
                        {"name": event.author, "ds": ds.name, "tm": event.event_time},
                    )

    async def _merge_dataset(self, conn, ds: Dataset) -> None:
        await run_cypher(
            conn,
            self._graph,
            _MERGE_DATASET,
            {"name": ds.name, "ns": ds.namespace},
        )

    async def upstream(self, name: str) -> Neighbors:
        """Datasets ``name`` is (transitively) derived from — its provenance."""
        rows = await fetch(self._pool, self._graph, _UPSTREAM, {"name": name}, columns=2)
        return Neighbors(dataset=name, related=[DatasetRef(name=r[0], namespace=r[1]) for r in rows])

    async def downstream(self, name: str) -> Neighbors:
        """Datasets that are (transitively) derived from ``name`` — its impact."""
        rows = await fetch(self._pool, self._graph, _DOWNSTREAM, {"name": name}, columns=2)
        return Neighbors(dataset=name, related=[DatasetRef(name=r[0], namespace=r[1]) for r in rows])

    async def producers(self, name: str) -> Producers:
        """The runs that wrote ``name`` — who / when / how (the commit-author answer)."""
        rows = await fetch(self._pool, self._graph, _PRODUCERS, {"name": name}, columns=4)
        return Producers(
            dataset=name,
            producers=[
                ProducerInfo(run_id=r[0], author=r[1], event_time=r[2], event_type=r[3]) for r in rows
            ],
        )

    async def creator(self, name: str) -> Creator:
        """Who created ``name`` — the verified principal on the catalog create event."""
        rows = await fetch(self._pool, self._graph, _CREATOR, {"name": name}, columns=1)
        return Creator(dataset=name, creator=rows[0][0] if rows else None)

    async def graph(self, name: str) -> LineageGraph:
        """The connected dataset-lineage subgraph around ``name`` (nodes + edges)."""
        up = await self.upstream(name)
        down = await self.downstream(name)
        namespaces: dict[str, str | None] = {name: await self._dataset_namespace(name)}
        for ref in (*up.related, *down.related):
            namespaces.setdefault(ref.name, ref.namespace)
        names = list(namespaces)
        edge_rows = await fetch(self._pool, self._graph, _GRAPH_EDGES, {"names": names}, columns=2)
        return LineageGraph(
            root=name,
            nodes=[GraphNode(id=n, namespace=ns) for n, ns in namespaces.items()],
            edges=[GraphEdge(source=r[0], target=r[1]) for r in edge_rows],
        )

    async def _dataset_namespace(self, name: str) -> str | None:
        rows = await fetch(self._pool, self._graph, _DATASET_NS, {"name": name}, columns=1)
        return rows[0][0] if rows else None
