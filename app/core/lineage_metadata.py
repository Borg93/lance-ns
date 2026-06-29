"""Embed lineage coordinates *into the Lance file itself* at table creation (#21).

The catalog already links a table to its lineage by a convention — the canonical id is the lineage
``Dataset`` name and the ``WROTE`` edge carries the Lance version. But nothing is written *into the
data*, so a copied/moved Lance dataset loses its lineage coordinates. Here we stamp those coordinates
onto the Arrow **schema metadata** of the create payload, so the Lance file is **self-describing**:
``lineage.dataset_id`` / ``lineage.namespace`` / ``lineage.create_run_id`` / ``lineage.created_by`` can
be read straight off the table and reconciled to the lineage graph without the catalog.

``create_run_id`` is the *same* run id the catalog emits in the OpenLineage create event, so the file
points at its exact creating run in the graph.
"""

from __future__ import annotations

import pyarrow as pa

#: Schema-metadata key prefix; the lineage service / a consumer reads these straight off the Lance table.
_KEY_DATASET_ID = "lineage.dataset_id"
_KEY_NAMESPACE = "lineage.namespace"
_KEY_CREATE_RUN_ID = "lineage.create_run_id"
_KEY_CREATED_BY = "lineage.created_by"


def build_lineage_metadata(
    *, table_id: str, namespace: str, run_id: str, created_by: str | None
) -> dict[str, str]:
    """The lineage coordinates to stamp into the Lance file's schema metadata at create."""
    return {
        _KEY_DATASET_ID: table_id,
        _KEY_NAMESPACE: namespace,
        _KEY_CREATE_RUN_ID: run_id,
        _KEY_CREATED_BY: created_by or "",
    }


def inject_into_arrow_stream(stream: bytes, metadata: dict[str, str]) -> bytes:
    """Return the Arrow IPC stream with ``metadata`` merged into its schema metadata.

    Existing schema metadata is preserved; the ``metadata`` keys win on conflict. The record batches
    are unchanged — only the schema's key/value metadata gains the lineage coordinates, which Lance
    persists as the table's schema metadata at version 1.
    """
    reader = pa.ipc.open_stream(stream)
    table = reader.read_all()
    merged: dict[bytes, bytes] = {
        **(table.schema.metadata or {}),
        **{key.encode(): value.encode() for key, value in metadata.items()},
    }
    table = table.replace_schema_metadata(merged)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()
