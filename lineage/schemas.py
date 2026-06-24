"""Typed response schemas for the lineage API (Pydantic, snake_case)."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
