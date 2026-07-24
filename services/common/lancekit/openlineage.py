"""OpenLineage facet primitives — the spec-2-0-2 RunEvent contract, kernel-owned.

The shared half of lineage emission: the pieces BOTH the annotation write path
(``common.lancekit.lineage_emit``) and the batch derivers (``ratch.lineage``)
build — ``WriteResult``, the schema/columnLineage facets, and the standalone
``build_run_event`` mirror. Mirrors lance-ns ``services/common/openlineage.py``
so the constants (``SCHEMA_URL``, the facet ``_schemaURL``s, the ``run_id_for``
uuid5 namespace) match theirs — a pre-merge event and a merged event describe the
same run identically.

Kernel layer: pure over a pyarrow schema + measured stats, no ``Stage`` and no
pipeline import. The ``Stage``-aware measurement (``column_map``, ``measure_stage``,
``emit_stage_lineage``) lives up in ``ratch.lineage``, which imports from here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pyarrow as pa
from pydantic import BaseModel, Field

from common.lancekit.blobs import blob_field_names

# ── Spec constants — MUST match lance-ns services/common/openlineage.py at merge ──
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
_SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
_OUTPUT_STATS_FACET_URL = (
    "https://openlineage.io/spec/facets/1-0-2/OutputStatisticsOutputDatasetFacet.json"
)
_COLUMN_LINEAGE_FACET_URL = (
    "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
)
_DATASOURCE_FACET_URL = "https://openlineage.io/spec/facets/1-0-1/DatasourceDatasetFacet.json"
PRODUCER = "https://github.com/Borg93/lance-audio/tree/main/src/ratch"
# Same UUID5 namespace lance-ns uses, so a run id computed here == the one computed
# there for the same seed (redeliveries MERGE onto one :Run, never duplicate).
_RUN_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Borg93/lance-ns")

#: One field→field edge: (output_field, input_field, transformation_subtype).
#: Carried columns are "IDENTITY"; derived artifacts are "TRANSFORMATION".
ColumnEdge = tuple[str, str, str]


class WriteResult(BaseModel):
    """The measured outcome of one write — mirrors lance-ns's WriteResult.

    Field names/shape match theirs on purpose so ``build_run_event`` (ours or theirs)
    consumes it unchanged.
    """

    version: int
    row_count: int
    size_bytes: int
    fields: list[dict[str, str]] = Field(default_factory=list)
    column_map: list[ColumnEdge] = Field(default_factory=list)


def _type_label(dtype: pa.DataType) -> str:
    """Concise lineage type label — vector/binary specialised, else pyarrow repr
    (blobs are labelled in ``facet_fields``, which knows the blob column names)."""
    if pa.types.is_fixed_size_list(dtype) or pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
        return f"array<{dtype.value_type}>"
    if pa.types.is_binary(dtype) or pa.types.is_large_binary(dtype):
        return "binary"
    return str(dtype)


def facet_fields(schema: pa.Schema) -> list[dict[str, str]]:
    """``SchemaDatasetFacet.fields`` — ``[{"name","type"}]`` per column, blob-aware.
    Mirrors lance-ns common/schema.facet_fields (blob → "blob")."""
    blobs = set(blob_field_names(schema))
    return [
        {"name": f.name, "type": "blob" if f.name in blobs else _type_label(f.type)}
        for f in schema
    ]


def run_id_for(seed: str) -> str:
    """Deterministic spec-valid UUID runId for a seed (e.g. ``"<stage>-<token>"``).
    Same uuid5 namespace as lance-ns so redeliveries merge onto one run."""
    return str(uuid.uuid5(_RUN_ID_NAMESPACE, seed))


def build_run_event(
    *,
    operation: str,
    job_namespace: str,
    job_name: str,
    inputs: list[tuple[str, str]],
    output_namespace: str,
    output_name: str,
    event_time: str,
    result: WriteResult,
    source_uri: str | None = None,
    event_type: str = "COMPLETE",
    error_message: str | None = None,
    seed: str | None = None,
) -> dict[str, Any]:
    """A minimal, spec-2-0-2 OpenLineage ``RunEvent`` (standalone mirror).

    Prefer lance-ns's ``medallion.schemas.events.build_run_event`` when merged — pass
    it to ``emit_stage_lineage(builder=...)``. This exists so a pre-merge run can emit
    the same-shaped event; keep it faithful, don't extend it past their facets.
    """
    run_id = run_id_for(seed or f"{operation}-{output_name}")
    output_facets: dict[str, Any] = {
        "schema": {"_producer": PRODUCER, "_schemaURL": _SCHEMA_FACET_URL, "fields": result.fields},
        "outputStatistics": {
            "_producer": PRODUCER,
            "_schemaURL": _OUTPUT_STATS_FACET_URL,
            "rowCount": result.row_count,
            "size": result.size_bytes,
        },
    }
    if result.column_map:
        output_facets["columnLineage"] = _column_lineage_facet(result.column_map, inputs)
    if source_uri is not None:
        output_facets["dataSource"] = {
            "_producer": PRODUCER,
            "_schemaURL": _DATASOURCE_FACET_URL,
            "name": output_name,
            "uri": source_uri,
        }
    run_facets: dict[str, Any] = {}
    if error_message is not None:
        run_facets["errorMessage"] = {
            "_producer": PRODUCER,
            "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ErrorMessageRunFacet.json",
            "message": error_message,
            "programmingLanguage": "PYTHON",
        }
    return {
        "eventType": event_type,
        "eventTime": event_time,
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
        "run": {"runId": run_id, "facets": run_facets},
        "job": {"namespace": job_namespace, "name": job_name},
        "inputs": [{"namespace": ns, "name": name} for ns, name in inputs],
        "outputs": [{"namespace": output_namespace, "name": output_name, "facets": output_facets}],
    }


def _column_lineage_facet(
    edges: list[ColumnEdge], inputs: list[tuple[str, str]]
) -> dict[str, Any]:
    """A ``ColumnLineageDatasetFacet``: per output field, its input field(s) + subtype."""
    in_ns, in_name = inputs[0] if inputs else ("", "")
    by_output: dict[str, list[dict[str, str]]] = {}
    for out_field, in_field, subtype in edges:
        by_output.setdefault(out_field, []).append(
            {
                "namespace": in_ns,
                "name": in_name,
                "field": in_field,
                "transformationType": "DIRECT",
                "transformationSubtype": subtype,
            }
        )
    return {
        "_producer": PRODUCER,
        "_schemaURL": _COLUMN_LINEAGE_FACET_URL,
        "fields": {out: {"inputFields": ins} for out, ins in by_output.items()},
    }
