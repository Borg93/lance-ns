"""OpenLineage RunEvent — the subset we ingest.

OpenLineage is an external standard whose wire format is camelCase (``eventType``,
``runId``); we read it with field aliases and expose snake_case in Python.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_MODEL = ConfigDict(extra="allow", populate_by_name=True)


class Dataset(BaseModel):
    """An OpenLineage dataset (a Lance table / source); ``name`` is the catalog id."""

    model_config = _MODEL
    namespace: str
    name: str


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
