"""OpenLineage RunEvent — the subset we ingest.

OpenLineage is an external standard whose wire format is camelCase (``eventType``,
``runId``); we read it with field aliases and expose snake_case in Python.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_MODEL = ConfigDict(extra="allow", populate_by_name=True)


class Dataset(BaseModel):
    """An OpenLineage dataset (a Lance table / source); ``name`` is the catalog id.

    ``facets`` carries the standard dataset facets (e.g. ``schema``, ``version``); we read
    the ``version`` facet on outputs to record which Lance dataset version a run produced.
    """

    model_config = _MODEL
    namespace: str
    name: str
    facets: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    """The job that produced a run (e.g. an ingest / lance-ray ETL job)."""

    model_config = _MODEL
    namespace: str
    name: str


class Run(BaseModel):
    """A single run of a job. ``facets.author`` carries the OIDC sub when present."""

    model_config = _MODEL
    run_id: str = Field(alias="runId")
    facets: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    """An OpenLineage run event (START/COMPLETE/…) with its inputs and outputs."""

    model_config = _MODEL
    event_type: str = Field(alias="eventType")
    event_time: str = Field(alias="eventTime")
    run: Run
    job: Job
    inputs: list[Dataset] = Field(default_factory=list)
    outputs: list[Dataset] = Field(default_factory=list)

    @property
    def author(self) -> str | None:
        """The run author (OIDC sub) from the ``author`` run facet, if any."""
        author = (self.run.facets or {}).get("author")
        if isinstance(author, dict):
            return author.get("name") or author.get("sub")
        return author if isinstance(author, str) else None

    @property
    def operation(self) -> str | None:
        """The catalog operation (e.g. ``create_table``) from the ``lance`` run facet, if any.

        Set by the catalog's emitter (``app.core.lineage_emit``); used to attach the
        ``(:User)-[:CREATED]->(:Dataset)`` edge on a table-create event.
        """
        lance = (self.run.facets or {}).get("lance")
        return lance.get("operation") if isinstance(lance, dict) else None

    def output_version(self, name: str) -> str | None:
        """The Lance dataset version this run produced for output ``name`` (``version`` facet).

        Ties a provenance run to the exact dataset version it wrote, so two refinement passes
        over the same table (e.g. add a column, then another) are distinguishable.
        """
        for ds in self.outputs:
            if ds.name == name:
                facet = (ds.facets or {}).get("version")
                version = facet.get("datasetVersion") if isinstance(facet, dict) else None
                return str(version) if version is not None else None
        return None
