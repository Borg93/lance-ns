"""Land external source objects into a bronze Lance blob table — the ingest head of the cascade.

Reads a provider-agnostic ``SourceAdapter`` (:mod:`common.sources`) and writes each object's bytes as a
managed blob-v2 column at file format 2.2, keeping the object's source URI as a column so provenance
survives in the data itself (the caller emits the ``source -> bronze`` lineage edge from ``source_uris``).
The per-stage ML then flows the blob forward (``compute._carry_forward``) and derives the silver artifacts.
"""

from __future__ import annotations

import lance
import pyarrow as pa
from common import schema
from common.sources import SourceAdapter
from lance import blob_array, blob_field
from pydantic import BaseModel

_INGEST_SCHEMA = pa.schema(
    [pa.field("id", pa.int64()), blob_field("payload"), pa.field("source_uri", pa.string())]
)


class IngestResult(BaseModel):
    """What one ingest produced: the bronze version + rows, the source URIs (for the lineage edge), and the
    written schema facet (blob-aware, for the WROTE edge)."""

    version: int
    row_count: int
    source_uris: list[str]
    fields: list[dict[str, str]]


def ingest_to_bronze(
    source: SourceAdapter, bronze_uri: str, storage_options: dict[str, str]
) -> IngestResult:
    """Write every object from ``source`` into a bronze blob-v2 table at 2.2 (``id, payload, source_uri``).

    Raises ``ValueError`` on an empty source: an empty bronze is almost always a mis-set prefix, and silently
    "succeeding" with zero rows would report a false success (and an input-less lineage edge) up the cascade.
    """
    # Whole batch resident in memory (bytes are copied again by blob_array): fine for the demo's small media;
    # for large media, stream in RecordBatch chunks (mode="overwrite" then "append") instead of one pa.table.
    objects = list(source.iter_objects())
    if not objects:
        raise ValueError(f"source yielded no objects; refusing to write an empty bronze at {bronze_uri!r}")
    table = pa.table(
        {
            # Positional id — the cascade is OVERWRITE-ONLY and compute._carry_forward re-reads blobs by the
            # same range(rows). If ingest ever gains append mode, derive a stable id (e.g. from source_uri).
            "id": pa.array(range(len(objects)), pa.int64()),
            "payload": blob_array([obj.data for obj in objects]),
            "source_uri": pa.array([obj.uri for obj in objects], pa.string()),
        },
        schema=_INGEST_SCHEMA,
    )
    # enable_stable_row_ids (create-time-only) — durable _rowid across compaction; forward-proofs the
    # positional-id note above, so a future append/upsert can key blob carry-forward by _rowid not range.
    dataset = lance.write_dataset(
        table, bronze_uri, mode="overwrite", storage_options=storage_options,
        data_storage_version="2.2", enable_stable_row_ids=True,
    )
    return IngestResult(
        version=int(dataset.version),
        row_count=dataset.count_rows(),
        source_uris=[obj.uri for obj in objects],
        fields=schema.facet_fields(dataset.schema),
    )
