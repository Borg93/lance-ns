"""Data-access layer for the lineage graph — all openCypher lives here.

The repository owns the two halves of the AGE graph: the **write** path (ingest an
OpenLineage run event → MERGE Run/Job/Dataset nodes + edges) and the **read** path
(traverse provenance / impact / producers). Endpoints depend on this class and never
see raw Cypher — per the layered architecture (handlers → repository → AGE).

Graph shape::

    (:Job {namespace, name})
    (:Run {run_id, author, event_type, event_time, producer, error_message})
    (:Dataset {name, namespace, source_uri, tags})  # name = catalog table id
    (:User {name})                            # an OIDC sub (the verified principal)
    (:Run)-[:OF_JOB]->(:Job)
    (:Run)-[:READ]->(:Dataset)                # inputs
    (:Run)-[:WROTE {version}]->(:Dataset)     # outputs (version = the Lance version produced)
    (:Dataset)-[:DERIVED_FROM]->(:Dataset)    # output <- input (dataset lineage)
    (:User)-[:CREATED]->(:Dataset)            # who created the table (catalog create event)

A **successful** run (``COMPLETE``) asserts data: it gets a versioned ``WROTE`` edge plus
``DERIVED_FROM`` (and ``CREATED`` on a catalog create). A **failed** run (``FAIL``/``ABORT``)
is still recorded — its ``Run`` carries the ``error_message`` and it keeps a ``WROTE`` edge so
``producers()`` surfaces the attempt — but with **no version** and **no ``DERIVED_FROM``**: a
failed run produced no data, so it must not assert lineage.

Datasets are MERGEd on ``{name}`` only (then ``namespace`` / ``source_uri`` / ``tags`` are SET)
so a dataset referenced by several runs is never duplicated.
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
    Runs,
    RunStatus,
)

# Must match app.core.lineage_emit.CREATE_TABLE — the OpenLineage ``lance`` facet operation the
# catalog emits on create, which keys the (:User)-[:CREATED]->(:Dataset) edge below (wire contract).
_CREATE_TABLE_OP: Final = "create_table"

_MERGE_JOB: Final = "MERGE (j:Job {namespace:$ns, name:$nm}) RETURN 1"
# The (:Run) node folds the whole lifecycle so /runs is durable (survives restart, replica-shared)
# instead of folding an in-memory buffer: event_type IS the current state and event_time IS
# updated_at (both last-event-wins via the repeated SET); started_at keeps the first event's time;
# events_count counts the lifecycle events seen. job is denormalised so /runs needs no OF_JOB join.
_MERGE_RUN: Final = (
    "MERGE (r:Run {run_id:$rid}) "
    "SET r.event_type=$et, r.event_time=$tm, r.author=$au, r.producer=$pr, r.error_message=$err, "
    "r.job=$job, r.started_at=coalesce(r.started_at, $tm), r.events_count=coalesce(r.events_count, 0)+1 "
    "RETURN 1"
)
# Progress + outputs ride only some events (RUNNING carries progress; only the terminal event names
# the outputs), so they are SET in their own conditional statements — never clobbered back to null.
_SET_RUN_PROGRESS: Final = (
    "MATCH (r:Run {run_id:$rid}) SET r.progress_done=$pd, r.progress_total=$pt RETURN 1"
)
_SET_RUN_OUTPUTS: Final = "MATCH (r:Run {run_id:$rid}) SET r.outputs=$outs RETURN 1"
_LIST_RUNS: Final = (
    "MATCH (r:Run) RETURN r.run_id, r.job, r.author, r.event_type, r.progress_done, r.progress_total, "
    "r.error_message, r.started_at, r.event_time, r.events_count, r.outputs"
)
_LINK_RUN_JOB: Final = (
    "MATCH (r:Run {run_id:$rid}), (j:Job {namespace:$ns, name:$nm}) MERGE (r)-[:OF_JOB]->(j) RETURN 1"
)
_MERGE_DATASET: Final = "MERGE (d:Dataset {name:$name}) SET d.namespace=$ns RETURN 1"
# Storage location + governance tags are SET only when the event carries them, so a later run
# that omits the dataSource/tags facet never clobbers what an earlier run recorded.
_SET_DATASET_SRC: Final = "MATCH (d:Dataset {name:$name}) SET d.source_uri=$src RETURN 1"
_SET_DATASET_TAGS: Final = "MATCH (d:Dataset {name:$name}) SET d.tags=$tags RETURN 1"
_LINK_READ: Final = "MATCH (r:Run {run_id:$rid}), (d:Dataset {name:$name}) MERGE (r)-[:READ]->(d) RETURN 1"
# The WROTE edge carries the Lance dataset version this run produced (from the OpenLineage
# ``version`` facet), so two refinement passes over one table are distinguishable in producers().
_LINK_WROTE: Final = "MATCH (r:Run {run_id:$rid}), (d:Dataset {name:$name}) MERGE (r)-[:WROTE]->(d) RETURN 1"
# AGE binds a ``$param`` in a standalone ``MATCH ... SET`` but silently drops one in a ``SET`` that
# follows ``MERGE`` on an edge in the *same* statement (verified on AGE 1.5.0/PG16), so the version
# is written in its own statement — mirroring how dataSource/tags are set on the Dataset node.
_SET_WROTE_VERSION: Final = (
    "MATCH (r:Run {run_id:$rid})-[w:WROTE]->(d:Dataset {name:$name}) SET w.version=$ver RETURN 1"
)
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
    "MATCH (r:Run)-[w:WROTE]->(d:Dataset {name:$name}) "
    "RETURN r.run_id, r.author, r.event_time, r.event_type, w.version, r.producer, r.error_message"
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
# nodes are fetched in one shot (name set), and edges are filtered to that name set.
_GRAPH_NODES: Final = (
    "MATCH (d:Dataset) WHERE d.name IN $names RETURN d.name, d.namespace, d.source_uri, d.tags"
)
_GRAPH_EDGES: Final = (
    "MATCH (a:Dataset)-[:DERIVED_FROM]->(b:Dataset) "
    "WHERE a.name IN $names AND b.name IN $names RETURN DISTINCT a.name, b.name"
)


def _tags_from(value: object) -> list[str]:
    """Split the comma-joined ``tags`` node property back into a list (``None``/"" → [])."""
    return value.split(",") if isinstance(value, str) and value else []


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
                    "pr": event.producer or "",
                    "err": event.error_message or "",
                    "job": f"{event.job.namespace}/{event.job.name}",
                },
            )
            progress = event.progress
            if progress is not None:
                await run_cypher(
                    conn,
                    self._graph,
                    _SET_RUN_PROGRESS,
                    {"rid": event.run.run_id, "pd": progress[0], "pt": progress[1]},
                )
            output_names = [ds.name for ds in event.outputs]
            if output_names:
                await run_cypher(
                    conn,
                    self._graph,
                    _SET_RUN_OUTPUTS,
                    {"rid": event.run.run_id, "outs": ",".join(output_names)},
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
                # A failed run keeps a WROTE edge (so producers() shows the attempt) but no version —
                # it produced no data, so it must not claim to have written a Lance version.
                await run_cypher(conn, self._graph, _LINK_WROTE, {"rid": event.run.run_id, "name": ds.name})
                version = event.output_version(ds.name) if event.is_success else None
                if version:
                    await run_cypher(
                        conn,
                        self._graph,
                        _SET_WROTE_VERSION,
                        {"rid": event.run.run_id, "name": ds.name, "ver": version},
                    )
            # Only a successful run asserts lineage: a failed run derived nothing.
            if event.is_success:
                for out in event.outputs:
                    for inp in event.inputs:
                        # An in-place refinement (reads and writes the same table — e.g. add a column)
                        # bumps the version via WROTE; it is NOT a self-DERIVED_FROM edge.
                        if out.name == inp.name:
                            continue
                        await run_cypher(
                            conn,
                            self._graph,
                            _DERIVED_FROM,
                            {"on": out.name, "inp": inp.name},
                        )
            # A successful catalog "create_table" event carries the verified author → record who
            # created the table as a first-class (:User)-[:CREATED]->(:Dataset) edge.
            if event.is_success and event.operation == _CREATE_TABLE_OP and event.author:
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
        if ds.source_uri:
            await run_cypher(conn, self._graph, _SET_DATASET_SRC, {"name": ds.name, "src": ds.source_uri})
        if ds.tags:
            await run_cypher(
                conn, self._graph, _SET_DATASET_TAGS, {"name": ds.name, "tags": ",".join(ds.tags)}
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
        """The runs that wrote (or failed to write) ``name`` — who / when / how / version / error."""
        rows = await fetch(self._pool, self._graph, _PRODUCERS, {"name": name}, columns=7)
        return Producers(
            dataset=name,
            producers=[
                ProducerInfo(
                    run_id=r[0],
                    author=r[1],
                    event_time=r[2],
                    event_type=r[3],
                    dataset_version=(r[4] or None),
                    producer=(r[5] or None),
                    error_message=(r[6] or None),
                )
                for r in rows
            ],
        )

    async def list_runs(self) -> Runs:
        """Every run's current lifecycle state, folded onto its ``(:Run)`` node in AGE.

        Durable replacement for the in-memory fold: survives a restart and is shared across replicas.
        ``event_type``/``event_time`` are the last-event-wins state/updated_at; ``""`` maps back to None.
        """
        rows = await fetch(self._pool, self._graph, _LIST_RUNS, columns=11)
        runs = [
            RunStatus(
                run_id=r[0],
                job=(r[1] or None),
                author=(r[2] or None),
                state=(r[3] or None),
                progress_done=r[4],
                progress_total=r[5],
                error_message=(r[6] or None),
                started_at=(r[7] or None),
                updated_at=(r[8] or None),
                events=int(r[9] or 0),
                outputs=_tags_from(r[10]),
            )
            for r in rows
        ]
        runs.sort(key=lambda run: run.updated_at or "", reverse=True)
        return Runs(runs=runs)

    async def creator(self, name: str) -> Creator:
        """Who created ``name`` — the verified principal on the catalog create event."""
        rows = await fetch(self._pool, self._graph, _CREATOR, {"name": name}, columns=1)
        return Creator(dataset=name, creator=rows[0][0] if rows else None)

    async def graph(self, name: str) -> LineageGraph:
        """The connected dataset-lineage subgraph around ``name`` (nodes + edges).

        Each node carries its storage location (``source_uri``) and governance ``tags`` so a
        DAG view can show *where* each table lives and *how* it is classified, not just its name.
        """
        up = await self.upstream(name)
        down = await self.downstream(name)
        names = list(dict.fromkeys([name, *(r.name for r in up.related), *(r.name for r in down.related)]))
        prop_rows = await fetch(self._pool, self._graph, _GRAPH_NODES, {"names": names}, columns=4)
        props = {r[0]: r for r in prop_rows}
        edge_rows = await fetch(self._pool, self._graph, _GRAPH_EDGES, {"names": names}, columns=2)
        return LineageGraph(
            root=name,
            nodes=[
                GraphNode(
                    id=n,
                    namespace=(props[n][1] if n in props else None),
                    source_uri=(props[n][2] if n in props else None),
                    tags=_tags_from(props[n][3] if n in props else None),
                )
                for n in names
            ],
            edges=[GraphEdge(source=r[0], target=r[1]) for r in edge_rows],
        )
