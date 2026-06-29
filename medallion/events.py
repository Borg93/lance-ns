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

#: Standard ``DatasetVersionDatasetFacet`` schema URL → the lineage WROTE edge records the Lance version.
_VERSION_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-0-1/DatasetVersionDatasetFacet.json"
    "#/$defs/DatasetVersionDatasetFacet"
)


def _dataset(namespace: str, name: str, version: int | None = None) -> dict[str, Any]:
    ds: dict[str, Any] = {"namespace": namespace, "name": name}
    if version is not None:
        ds["facets"] = {
            "version": {
                "_producer": _PRODUCER,
                "_schemaURL": _VERSION_FACET_SCHEMA,
                "datasetVersion": str(version),
            }
        }
    return ds


def build_run_event(
    *,
    operation: str,
    author: str | None,
    job_namespace: str,
    inputs: list[tuple[str, str]],
    output_namespace: str,
    output_name: str,
    version: int = 1,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the OpenLineage ``RunEvent`` (wire JSON) for one medallion transform.

    ``inputs`` is a list of ``(namespace, name)`` upstream datasets (empty for the raw producer, which has
    no upstream). The single output carries the standard version facet so the ``WROTE`` edge records the
    Lance version. ``run_id`` is injected so the producer can correlate the run across the cascade.
    """
    run_facets: dict[str, Any] = {"lance": {"operation": operation, "version": version}}
    if author:
        run_facets["author"] = {"name": author, "sub": author}
    return {
        "eventType": "COMPLETE",
        "eventTime": datetime.now(UTC).isoformat(),
        "producer": _PRODUCER,
        "run": {"runId": run_id or str(uuid.uuid4()), "facets": run_facets},
        "job": {"namespace": job_namespace, "name": operation},
        "inputs": [_dataset(ns, name) for ns, name in inputs],
        "outputs": [_dataset(output_namespace, output_name, version)],
    }
