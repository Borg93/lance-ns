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

    ``facets`` carries the standard OpenLineage dataset facets; we read several:
    ``version`` (which Lance version a run produced), ``dataSource`` (where the table
    physically lives — the S3-compatible location), and ``tags`` (governance labels).
    """

    model_config = _MODEL
    namespace: str
    name: str
    facets: dict[str, Any] = Field(default_factory=dict)

    @property
    def source_uri(self) -> str | None:
        """Where this dataset physically lives, from the standard ``dataSource`` facet.

        For a Lance table this is the S3-compatible URI (e.g. ``s3://lakehouse/silver/features``).
        """
        facet = (self.facets or {}).get("dataSource")
        uri = facet.get("uri") if isinstance(facet, dict) else None
        return uri if isinstance(uri, str) and uri else None

    @property
    def tags(self) -> list[str]:
        """Governance labels from the standard ``tags`` facet, as ``key=value`` strings."""
        facet = (self.facets or {}).get("tags")
        items = facet.get("tags") if isinstance(facet, dict) else None
        if not isinstance(items, list):
            return []
        labels: list[str] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("key"):
                continue
            value = item.get("value")
            labels.append(f"{item['key']}={value}" if value not in (None, "") else str(item["key"]))
        return labels


class Job(BaseModel):
    """The compute job that produced a run — for us a Ray job (Ray is the compute engine).

    ``facets`` carries the standard ``ownership`` (who owns the job) and ``jobType``
    (``processingType`` BATCH/STREAMING, ``integration`` = RAY, ``jobType`` = ETL /
    TRANSFORMATION) facets.
    """

    model_config = _MODEL
    namespace: str
    name: str
    facets: dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    """A single run of a job. ``facets.author`` carries the OIDC sub when present."""

    model_config = _MODEL
    run_id: str = Field(alias="runId")
    facets: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    """An OpenLineage run event (START/RUNNING/COMPLETE/FAIL/ABORT) with its inputs and outputs."""

    model_config = _MODEL
    event_type: str = Field(alias="eventType")
    event_time: str = Field(alias="eventTime")
    producer: str | None = Field(default=None)
    run: Run
    job: Job
    inputs: list[Dataset] = Field(default_factory=list)
    outputs: list[Dataset] = Field(default_factory=list)

    @property
    def author(self) -> str | None:
        """The run author (OIDC sub) — our custom ``author`` run facet, else standard ``ownership``.

        Prefers the ``author`` run facet (set by our producers/catalog); falls back to the
        first owner in the standard ``ownership`` job facet so events from external
        OpenLineage producers (Marquez-style) still attribute an owner.
        """
        author = (self.run.facets or {}).get("author")
        if isinstance(author, dict):
            name = author.get("name") or author.get("sub")
            if name:
                return name
        elif isinstance(author, str) and author:
            return author
        owners = ((self.job.facets or {}).get("ownership") or {}).get("owners")
        if isinstance(owners, list):
            for owner in owners:
                if isinstance(owner, dict) and owner.get("name"):
                    return owner["name"]
        return None

    @property
    def error_message(self) -> str | None:
        """The failure message from the standard ``errorMessage`` run facet, if any."""
        facet = (self.run.facets or {}).get("errorMessage")
        if isinstance(facet, dict):
            message = facet.get("message")
            return message if isinstance(message, str) and message else None
        return None

    @property
    def is_success(self) -> bool:
        """A terminal *successful* run — only these assert produced data / lineage."""
        return self.event_type.upper() == "COMPLETE"

    @property
    def is_failure(self) -> bool:
        """A terminal *failed* run (FAIL/ABORT) — recorded, but it produced no data."""
        return self.event_type.upper() in {"FAIL", "ABORT"}

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
