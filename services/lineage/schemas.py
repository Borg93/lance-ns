"""Typed response schemas for the lineage API (Pydantic, snake_case)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReconcileState(StrEnum):
    """Result of reconciling the lineage graph's recorded version against the on-disk Lance version."""

    IN_SYNC = "in_sync"  # graph and storage agree
    STORAGE_AHEAD = "storage_ahead"  # data changed on disk without a lineage event (drift)
    GRAPH_AHEAD = "graph_ahead"  # lineage claims a newer version than exists on disk (inconsistency)
    UNTRACKED = "untracked"  # data exists on disk but the graph has no versioned write (no lineage)
    MISSING_ON_STORAGE = "missing_on_storage"  # graph records a version but the dataset isn't on disk
    ABSENT = "absent"  # neither side has it


class ReconcileStatus(BaseModel):
    """Whether a dataset's lineage-graph version matches its actual on-disk Lance version (#23)."""

    dataset: str
    graph_version: int | None = None
    storage_version: int | None = None
    in_sync: bool
    status: ReconcileState


class DatasetRef(BaseModel):
    """A dataset node returned from a graph traversal."""

    name: str
    namespace: str | None = None


class ProducerInfo(BaseModel):
    """A run that wrote (or attempted to write) a dataset — who / when / how / version.

    A **failed** run (``event_type`` FAIL/ABORT) appears here too, with no
    ``dataset_version`` and an ``error_message`` — it tried but produced no data.
    """

    run_id: str
    author: str | None = None
    event_time: str | None = None
    event_type: str | None = None
    dataset_version: str | None = None
    producer: str | None = None
    error_message: str | None = None


class Neighbors(BaseModel):
    """Datasets related to ``dataset`` (upstream provenance or downstream impact)."""

    dataset: str
    related: list[DatasetRef]


class Producers(BaseModel):
    """The runs that produced ``dataset``."""

    dataset: str
    producers: list[ProducerInfo]


class Creator(BaseModel):
    """Who created ``dataset`` — the verified catalog principal at create time (or ``None``)."""

    dataset: str
    creator: str | None = None


class SchemaField(BaseModel):
    """One column in a dataset's persisted per-version schema (from the standard ``schema`` facet)."""

    name: str
    type: str = ""
    description: str | None = None


class DatasetSchema(BaseModel):
    """The column schema recorded for ``dataset`` at ``version`` (the ``WROTE`` edge's schema). (#24)

    ``version`` is the Lance version this schema belongs to; ``None`` with empty ``fields`` means no
    schema has been persisted for the dataset (or the requested version) yet.
    """

    dataset: str
    version: int | None = None
    fields: list[SchemaField] = Field(default_factory=list)


class ColumnRef(BaseModel):
    """A column identified by its owning dataset + field name (#24).

    ``dataset`` is REQUIRED and is the governance handle: a column is visible iff the caller can read
    its owning ``table:<dataset>``, so column queries filter on it (never on the field).
    """

    dataset: str
    field: str
    namespace: str | None = None
    type: str | None = None


class ColumnNeighbors(BaseModel):
    """Columns related to ``(dataset, field)`` — its column-level provenance (upstream) or impact."""

    dataset: str
    field: str
    related: list[ColumnRef] = Field(default_factory=list)


class ColumnNode(BaseModel):
    """A column node in the column-lineage subgraph."""

    dataset: str
    field: str
    type: str | None = None


class ColumnEdge(BaseModel):
    """A field-to-field derivation edge (data flows ``source`` → ``target``); the transformation kind +
    the ``masking`` governance bit ride the edge."""

    source_dataset: str
    source_field: str
    target_dataset: str
    target_field: str
    transformation_type: str = ""
    transformation_subtype: str = ""
    masking: bool = False
    description: str = ""
    kind: str = "derived_from_column"


class ColumnGraph(BaseModel):
    """The column-level lineage subgraph around ``root`` (nodes + edges) — the column analogue of the
    dataset ``LineageGraph``, for a field-to-field DAG view."""

    root: str
    columns: list[ColumnNode] = Field(default_factory=list)
    edges: list[ColumnEdge] = Field(default_factory=list)


class GraphNode(BaseModel):
    """A dataset node in the lineage graph (``id`` is the catalog table id).

    ``source_uri`` is where the table physically lives (the S3-compatible location, from
    the ``dataSource`` facet) and ``tags`` are its governance labels (from the ``tags`` facet).
    """

    id: str
    namespace: str | None = None
    kind: str = "dataset"
    source_uri: str | None = None
    tags: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """A dataset-level lineage edge: ``source`` is derived from ``target``."""

    source: str
    target: str
    kind: str = "derived_from"


class LineageGraph(BaseModel):
    """The connected lineage subgraph around ``root`` — nodes + edges for a DAG view.

    Mirrors what Marquez's graph endpoint feeds its UI, trimmed to the dataset-level
    ``DERIVED_FROM`` lineage we model.
    """

    root: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class EventRecord(BaseModel):
    """One ingested OpenLineage event, Marquez-style (summary + the full event with facets)."""

    seq: int
    event_type: str | None = None
    event_time: str | None = None
    job: str | None = None
    author: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    event: dict[str, Any]


class Events(BaseModel):
    """The most-recent ingested OpenLineage events (newest first)."""

    events: list[EventRecord]


class DemoField(BaseModel):
    """A column of a Lance dataset version (name + Arrow type)."""

    name: str
    type: str


class DemoVersion(BaseModel):
    """One Lance version of a dataset — its number, time, and schema at that version."""

    version: int
    timestamp: str | None = None
    fields: list[DemoField] = Field(default_factory=list)


class DemoDataset(BaseModel):
    """A peek at a real Lance dataset on S3 — what's actually in storage and how it evolved."""

    name: str
    uri: str
    exists: bool
    current_version: int | None = None
    row_count: int | None = None
    versions: list[DemoVersion] = Field(default_factory=list)
    lineage_jsonb: dict[str, Any] | None = None
    error: str | None = None


class DemoDatasets(BaseModel):
    """The medallion datasets as they currently exist on S3 (demo data peek)."""

    datasets: list[DemoDataset]


class RunStatus(BaseModel):
    """The *current* status of a run, folded from its OpenLineage lifecycle events.

    Unlike the provenance graph (terminal-only), this is the live "where are we now" view:
    ``state`` is the latest run state (START→RUNNING→COMPLETE/FAIL), with progress + error.
    """

    run_id: str
    job: str | None = None
    author: str | None = None
    state: str | None = None
    outputs: list[str] = Field(default_factory=list)
    progress_done: int | None = None
    progress_total: int | None = None
    error_message: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    events: int = 0


class Runs(BaseModel):
    """Live run-status board (most-recently-active first)."""

    runs: list[RunStatus]
