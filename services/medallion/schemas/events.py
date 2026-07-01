"""OpenLineage RunEvent builders for the medallion services.

Each (dummy) Ray job emits a standard OpenLineage ``RunEvent`` describing what it did — ``inputs`` = the
upstream stage's dataset(s), ``outputs`` = the dataset it produced — which the lineage service ingests
into Apache AGE, growing the ``(:Dataset)-[:DERIVED_FROM]->(:Dataset)`` edge that *is* the medallion DAG.
Same wire format the lineage consumer already validates (``lineage.models.RunEvent``); the ``lance`` run
facet carries the operation + version, and an ``author`` facet stamps the persona.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

#: OpenLineage ``producer`` URI — identifies the software that emitted the event.
_PRODUCER = "https://github.com/Borg93/lance-ns/tree/main/medallion"

#: The repo the medallion services live in — the ``sourceCodeLocation`` job facet's git URL.
_REPO_URL = "https://github.com/Borg93/lance-ns"
#: Standard ``SourceCodeLocationJobFacet`` schema URL → *where the job's code lives* (git repo + path).
#: A HERE-DUMMY of what rask's runner will auto-derive from its git + pipeline once lance-ray OpenLineage
#: is wired (GOAL 3-real); today the medallion emitter asserts it from the known service location.
_SOURCE_LOCATION_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-1-0/SourceCodeLocationJobFacet.json"
    "#/$defs/SourceCodeLocationJobFacet"
)

#: Standard ``DatasetVersionDatasetFacet`` schema URL → the lineage WROTE edge records the Lance version.
_VERSION_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-0-1/DatasetVersionDatasetFacet.json"
    "#/$defs/DatasetVersionDatasetFacet"
)
#: Standard ``OutputStatisticsOutputDatasetFacet`` schema URL → the runtime-measured rows + on-disk bytes
#: the compute actually wrote (moves our lineage from producer-declared toward Marquez-grade). Output-only.
_OUTPUT_STATS_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-0-2/OutputStatisticsOutputDatasetFacet.json"
    "#/$defs/OutputStatisticsOutputDatasetFacet"
)
#: Standard ``DataQualityAssertionsDatasetFacet`` schema URL → the validator's assertions on the produced
#: dataset; a ``success: false`` entry is the record of a batch the quality gate blocked from promotion.
_DATA_QUALITY_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-1-0/DataQualityAssertionsDatasetFacet.json"
    "#/$defs/DataQualityAssertionsDatasetFacet"
)


def _dataset(
    namespace: str,
    name: str,
    version: int | None = None,
    row_count: int | None = None,
    size_bytes: int | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ds: dict[str, Any] = {"namespace": namespace, "name": name}
    facets: dict[str, Any] = {}
    if version is not None:
        facets["version"] = {
            "_producer": _PRODUCER,
            "_schemaURL": _VERSION_FACET_SCHEMA,
            "datasetVersion": str(version),
        }
    # outputStatistics is an OUTPUT facet — present only when the compute actually measured a write (the
    # raw producer / dummy emit omits it). Inputs never pass row_count, so they never carry it.
    if row_count is not None or size_bytes is not None:
        facets["outputStatistics"] = {
            "_producer": _PRODUCER,
            "_schemaURL": _OUTPUT_STATS_FACET_SCHEMA,
            "rowCount": row_count,
            "size": size_bytes,
        }
    # dataQualityAssertions is an OUTPUT facet — present only when the quality gate validated the write.
    if assertions:
        facets["dataQualityAssertions"] = {
            "_producer": _PRODUCER,
            "_schemaURL": _DATA_QUALITY_FACET_SCHEMA,
            "assertions": assertions,
        }
    if facets:
        ds["facets"] = facets
    return ds


def _job_source_location() -> dict[str, Any]:
    """The standard ``sourceCodeLocation`` job facet — where this job's code lives.

    A HERE-DUMMY (like the ``outputStatistics`` / ``dataQualityAssertions`` facets): the medallion services
    all live in this repo under ``services/medallion``, so the emitter asserts that git location directly.
    rask's runner will auto-derive the real value (its git repo + pipeline path) when lance-ray OpenLineage
    lands (GOAL 3-real) — same facet, measured instead of declared.
    """
    return {
        "_producer": _PRODUCER,
        "_schemaURL": _SOURCE_LOCATION_FACET_SCHEMA,
        "type": "git",
        "url": _REPO_URL,
        "path": "services/medallion",
        "branch": "main",
    }


def build_run_event(
    *,
    operation: str,
    author: str | None,
    job_namespace: str,
    inputs: list[tuple[str, str]],
    output_namespace: str,
    output_name: str,
    version: int = 1,
    row_count: int | None = None,
    size_bytes: int | None = None,
    assertions: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the OpenLineage ``RunEvent`` (wire JSON) for one medallion transform.

    ``inputs`` is a list of ``(namespace, name)`` upstream datasets (empty for the raw producer, which has
    no upstream). The single output carries the standard version facet so the ``WROTE`` edge records the
    Lance version, plus — when the compute measured the write (``row_count`` / ``size_bytes`` set) — the
    standard ``outputStatistics`` facet with the rows + on-disk bytes it produced, plus — when the quality
    gate validated the write (``assertions`` set) — the standard ``dataQualityAssertions`` facet. ``run_id``
    is injected so the producer can correlate the run across the cascade.
    """
    run_facets: dict[str, Any] = {"lance": {"operation": operation, "version": version}}
    if author:
        run_facets["author"] = {"name": author, "sub": author}
    return {
        "eventType": "COMPLETE",
        "eventTime": datetime.now(UTC).isoformat(),
        "producer": _PRODUCER,
        "run": {"runId": run_id or str(uuid.uuid4()), "facets": run_facets},
        "job": {
            "namespace": job_namespace,
            "name": operation,
            "facets": {"sourceCodeLocation": _job_source_location()},
        },
        "inputs": [_dataset(ns, name) for ns, name in inputs],
        "outputs": [
            _dataset(
                output_namespace,
                output_name,
                version=version,
                row_count=row_count,
                size_bytes=size_bytes,
                assertions=assertions,
            )
        ],
    }
