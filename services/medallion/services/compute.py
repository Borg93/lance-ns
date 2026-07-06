"""The fake-Ray in-process Lance compute for the medallion cascade (the lance-ray seam, #25 / P1 #6).

Default OFF (``MEDALLION_COMPUTE_ENABLED``): the movers/producer stay dummy-emitters (lineage, no data).
When on, each stage does a **real** Lance write — the producer seeds ``raw_events``; each mover reads its
upstream Lance dataset, applies a stage transform, and writes the downstream one — so the emitted lineage
carries the **real** Lance version and the whole event-driven loop produces actual versioned data, not just
provenance.

This is the **same** ``read → transform → write → version`` contract a distributed Ray Data job
(``lance-ray`` on rask's KubeRay) fills in production; here it runs **in-process** so the cascade is
end-to-end testable without a Ray cluster. The compute operates on LANCE TYPES only: every stage carries
rows forward — tabular columns as tabular, vectors as vectors, blob columns of any media kind
re-materialised safely — and stamps a ``stage`` provenance column; what a stage derives from blob
payloads is dispatched on CONTENT by :mod:`medallion.services.derivers` (image → thumbnail+embedding;
unrecognised → untouched; tabular → no-op), so the same deployed mover binary serves every lane with
zero media config. Heavier per-stage ML (real encoders, captioning) is the distributed job's job at
rask. Blocking Lance/S3 IO; callers run it in the threadpool.
"""

from __future__ import annotations

from typing import Any, cast

import lance
import pyarrow as pa
from common import blobs, schema
from lance import blob_array, blob_field
from pydantic import BaseModel, Field

from medallion.services.derivers import derive_artifacts

_STAGE_COLUMN = "stage"


class WriteResult(BaseModel):
    """The measured outcome of one fake-Ray Lance write — the new version + observed output statistics.

    ``row_count`` / ``size_bytes`` are read straight off the just-written dataset (exact, not estimated),
    so the emitted OpenLineage ``outputStatistics`` facet carries what the job *actually* produced — the
    runtime-measured numbers that move our lineage from producer-declared toward Marquez-grade. Because the
    cascade writes with ``mode="overwrite"``, the whole dataset IS this run's output, so its on-disk size
    is the size this run wrote.
    """

    version: int
    row_count: int
    size_bytes: int
    #: ``SchemaDatasetFacet`` fields (``[{"name", "type"}]``, blob/vector-aware) of the written dataset —
    #: what the emit records on the WROTE edge so the lineage graph shows real media column types.
    fields: list[dict[str, str]] = Field(default_factory=list)


def measure(uri: str, storage_options: dict[str, str]) -> WriteResult:
    """Read the just-written dataset's version + exact output statistics (rows + on-disk bytes) + schema."""
    ds = lance.dataset(uri, storage_options=storage_options)
    # lance annotates ``DataStatistics.fields`` as a single ``FieldStatistics`` but returns a list at
    # runtime (upstream stub bug), so cast to the real shape before summing the per-field on-disk bytes.
    field_stats = cast("list[Any]", ds.stats.data_stats().fields)
    size_bytes = sum(stat.bytes_on_disk for stat in field_stats)
    return WriteResult(
        version=int(ds.version),
        row_count=ds.count_rows(),
        size_bytes=size_bytes,
        fields=schema.facet_fields(ds.schema),
    )


def seed_raw(uri: str, storage_options: dict[str, str], *, rows: int = 8) -> WriteResult:
    """Seed a small synthetic ``raw_events`` dataset — the fake lance-ray ingest at the head of the cascade.

    Overwrites any existing dataset (idempotent re-seed) and returns the resulting Lance version + the
    measured output statistics (rows + on-disk bytes) the emit records as an ``outputStatistics`` facet.
    """
    table = pa.table(
        {
            "id": pa.array(list(range(rows)), pa.int64()),
            "payload": pa.array([f"event-{i}" for i in range(rows)]),
        }
    )
    # data_storage_version="2.2" — the current Lance format (blob v2 + Map need it; pylance 8 still
    # defaults to 2.1). Overwrite-mode upgrades a pre-existing 2.1 dataset forward on the next run.
    # enable_stable_row_ids — row _rowid stays constant across compaction (which rewrites fragments and
    # invalidates row ADDRESSES). This is a CREATE-TIME-ONLY flag: it cannot be turned on later, so we set it
    # at the cascade head to keep durable row identity available (e.g. to key blob carry-forward by _rowid if
    # a stage ever gains append/upsert). Free on top of overwrite; the positional read path is unaffected.
    lance.write_dataset(
        table,
        uri,
        mode="overwrite",
        storage_options=storage_options,
        data_storage_version="2.2",
        enable_stable_row_ids=True,
    )
    return measure(uri, storage_options)


def has_blob_columns(uri: str, storage_options: dict[str, str]) -> bool:
    """Whether the dataset carries any blob-v2 column — the mover's Ray-path gate (blocking IO).

    The Ray stage job is not yet blob-safe (plain ``read_lance().map_batches()`` hits the ``to_table``
    blob-demotion landmine) and runs no artifact derivation, so a blob-carrying upstream must take the
    in-process path even when Ray is enabled.
    """
    return bool(blobs.blob_field_names(lance.dataset(uri, storage_options=storage_options).schema))


def transform_stage(
    from_uri: str, to_uri: str, storage_options: dict[str, str], *, stage: str
) -> WriteResult:
    """Read the upstream Lance dataset, transform, write the downstream dataset (the generic stage).

    Every stage stamps the ``stage`` provenance column (set, not appended twice, so re-running over an
    already-stamped upstream replaces the value), carries blob columns of ANY media kind through intact
    (``_carry_forward``), and derives whatever the blob CONTENT supports (``derive_artifacts`` — image →
    thumbnail+embedding, unrecognised → untouched, tabular → no-op). Returns the new downstream Lance
    version + the measured output statistics (rows + on-disk bytes) for the emit.
    """
    ds = lance.dataset(from_uri, storage_options=storage_options)
    out, blob_payloads = _carry_forward(ds, stage)
    out = derive_artifacts(out, blob_payloads)
    # 2.2 + stable row ids like seed_raw: every dataset the cascade writes is on the current format (so a blob
    # column never trips "Blob v2 requires file version >= 2.2" mid-cascade) and keeps durable row identity.
    lance.write_dataset(
        out,
        to_uri,
        mode="overwrite",
        storage_options=storage_options,
        data_storage_version="2.2",
        enable_stable_row_ids=True,
    )
    return measure(to_uri, storage_options)


def _carry_forward(ds: lance.LanceDataset, stage: str) -> tuple[pa.Table, dict[str, list[bytes]]]:
    """Read the upstream table and stamp the ``stage`` column, carrying any blob-v2 column through intact.

    A plain ``to_table()`` demotes a blob column to its descriptions struct (tagged with the legacy
    ``lance-encoding:blob`` key), which the 2.2 write then rejects — so blob columns are re-materialised
    via ``read_blobs`` + ``blob_array``. A stage with no blob column keeps the cheap straight-through
    path. Returns the stamped table AND the materialised blob payloads per column, so a media stage can
    derive artifacts without a second ``read_blobs`` pass.
    """
    blob_cols = blobs.blob_field_names(ds.schema)
    if not blob_cols:
        return _stamp_stage(ds.to_table(), stage), {}

    # Full-materialise each blob column into memory (read_blobs by positional indices 0..N-1) — fine for
    # this in-process fake-Ray stand-in over the cascade's small overwrite-written datasets (contiguous
    # row ids); a distributed job would stream instead. `range(rows)` aligns with `to_table()` only because
    # the cascade is overwrite-only (no soft-deleted rows to shift positions).
    rows = ds.count_rows()
    plain = ds.to_table(
        columns=[f.name for f in ds.schema if f.name not in blob_cols and f.name != _STAGE_COLUMN]
    )
    columns: dict[str, Any] = {}
    fields: list[pa.Field] = []
    blob_payloads: dict[str, list[bytes]] = {}
    for f in ds.schema:
        if f.name == _STAGE_COLUMN:
            continue  # re-stamped below so the value reflects this stage, not the upstream's
        if f.name in blob_cols:
            payloads = [payload for _addr, payload in ds.read_blobs(f.name, indices=list(range(rows)))]
            blob_payloads[f.name] = payloads
            fields.append(blob_field(f.name))
            columns[f.name] = blob_array(payloads)
        else:
            fields.append(plain.schema.field(f.name))
            columns[f.name] = plain.column(f.name)
    fields.append(pa.field(_STAGE_COLUMN, pa.string()))
    columns[_STAGE_COLUMN] = pa.array([stage] * rows, pa.string())
    return pa.table(columns, schema=pa.schema(fields)), blob_payloads


def _stamp_stage(table: pa.Table, stage: str) -> pa.Table:
    """Set (or append) the ``stage`` provenance column on ``table``."""
    field = pa.field(_STAGE_COLUMN, pa.string())
    marker = pa.array([stage] * table.num_rows, pa.string())
    if _STAGE_COLUMN in table.column_names:
        return table.set_column(table.schema.get_field_index(_STAGE_COLUMN), field, marker)
    return table.append_column(field, marker)
