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
from common.sources import SourceAdapter, SourceObject
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


def _chunk_table(chunk: list[SourceObject], first_id: int) -> pa.Table:
    """One chunk's rows as an Arrow table; ``first_id`` keeps the positional id GLOBAL across chunks."""
    return pa.table(
        {
            # Positional id — the cascade is OVERWRITE-ONLY and compute._carry_forward re-reads blobs by
            # the same range(rows); appended chunks preserve insertion order, so the global offset keeps
            # id == position. If ingest ever gains true append mode, derive a stable id from source_uri.
            "id": pa.array(range(first_id, first_id + len(chunk)), pa.int64()),
            "payload": blob_array([obj.data for obj in chunk]),
            "source_uri": pa.array([obj.uri for obj in chunk], pa.string()),
        },
        schema=_INGEST_SCHEMA,
    )


def ingest_to_bronze(
    source: SourceAdapter,
    bronze_uri: str,
    storage_options: dict[str, str],
    *,
    max_objects: int = 10_000,
    max_total_bytes: int = 1 << 30,
    chunk_objects: int = 64,
    chunk_bytes: int = 64 << 20,
) -> IngestResult:
    """STREAM every object from ``source`` into a bronze blob-v2 table at 2.2 (``id, payload, source_uri``).

    Raises ``ValueError`` on an empty source: an empty bronze is almost always a mis-set prefix, and silently
    "succeeding" with zero rows would report a false success (and an input-less lineage edge) up the cascade.

    STREAMING (2026-07-12, retires the whole-batch-in-memory posture): objects are written in chunks —
    the first chunk ``mode="overwrite"`` (which also sets the create-time-only
    ``enable_stable_row_ids``), the rest ``mode="append"`` — so memory high-water is ONE chunk plus the
    accumulated URI strings, regardless of source size. A chunk flushes on ``chunk_objects`` OR
    ``chunk_bytes``, WHICHEVER TRIPS FIRST: the object count alone would let 64 large images balloon a
    "chunk" toward the whole total ceiling (the flaw a review question exposed), so the byte bound is
    the real memory guarantee and the count bound is the fragment-hygiene knob (many tiny objects
    still batch into sensibly-sized Lance fragments instead of per-object commits). Neither number is
    a Dapr/NATS constraint — the bus never carries payload bytes (claim-check: events are pointers);
    these tune ONLY resident memory vs Lance commit/fragment churn. The CEILINGS remain the refusal
    guard (clear
    ``ValueError`` naming the env knob, mapped to 400 at the route) against a mis-pointed prefix: bounded
    memory does not make a million-object ingest a good idea. Two consequences, both deliberate:
    a multi-chunk ingest commits multiple Lance versions and the lineage WROTE edge records the FINAL one
    (versions are cheap; the edge's version is the readable-result handle); and a mid-ingest crash leaves a
    partial bronze with NO trigger published — harmless, because the cascade head only fires after success
    and the next ingest's first chunk overwrites from scratch (the same idempotent-overwrite contract the
    whole cascade rests on).
    """
    dataset: lance.LanceDataset | None = None
    chunk: list[SourceObject] = []
    chunk_size = 0
    source_uris: list[str] = []
    total_bytes = 0
    next_id = 0

    def flush(pending: list[SourceObject]) -> lance.LanceDataset:
        nonlocal next_id
        table = _chunk_table(pending, next_id)
        next_id += len(pending)
        if dataset is None:
            # enable_stable_row_ids (create-time-only) — durable _rowid across compaction; appends
            # inherit it. First chunk overwrites so a re-ingest always starts from scratch.
            return lance.write_dataset(
                table,
                bronze_uri,
                mode="overwrite",
                storage_options=storage_options,
                data_storage_version="2.2",
                enable_stable_row_ids=True,
            )
        return lance.write_dataset(
            table, bronze_uri, mode="append", storage_options=storage_options, data_storage_version="2.2"
        )

    for obj in source.iter_objects():
        chunk.append(obj)
        source_uris.append(obj.uri)
        total_bytes += len(obj.data)
        if len(source_uris) > max_objects:
            raise ValueError(
                f"source exceeds the ingest ceiling of {max_objects} objects "
                f"(MEDALLION_INGEST_MAX_OBJECTS); narrow the source prefix or raise the ceiling"
            )
        if total_bytes > max_total_bytes:
            raise ValueError(
                f"source exceeds the ingest ceiling of {max_total_bytes} total bytes "
                f"(MEDALLION_INGEST_MAX_TOTAL_BYTES); narrow the source prefix or raise the ceiling"
            )
        chunk_size += len(obj.data)
        if len(chunk) >= chunk_objects or chunk_size >= chunk_bytes:
            dataset = flush(chunk)
            chunk = []
            chunk_size = 0
    if chunk:
        dataset = flush(chunk)
    if dataset is None:
        raise ValueError(f"source yielded no objects; refusing to write an empty bronze at {bronze_uri!r}")
    return IngestResult(
        version=int(dataset.version),
        row_count=dataset.count_rows(),
        source_uris=source_uris,
        fields=schema.facet_fields(dataset.schema),
    )
