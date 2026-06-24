"""Typed response schemas for the lineage API (Pydantic, snake_case)."""

from __future__ import annotations

from pydantic import BaseModel


class DatasetRef(BaseModel):
    """A dataset node returned from a graph traversal."""

    name: str
    namespace: str | None = None


class ProducerInfo(BaseModel):
    """A run that wrote a dataset — the who / when / how answer."""

    run_id: str
    author: str | None = None
    event_time: str | None = None
    event_type: str | None = None


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
    """A dataset node in the lineage graph (``id`` is the catalog table id)."""

    id: str
    namespace: str | None = None
    kind: str = "dataset"


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
