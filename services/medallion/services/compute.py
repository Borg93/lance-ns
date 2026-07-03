"""The fake-Ray in-process Lance compute for the medallion cascade (the lance-ray seam, #25 / P1 #6).

Default OFF (``MEDALLION_COMPUTE_ENABLED``): the movers/producer stay dummy-emitters (lineage, no data).
When on, each stage does a **real** Lance write — the producer seeds ``raw_events``; each mover reads its
upstream Lance dataset, applies a stage transform, and writes the downstream one — so the emitted lineage
carries the **real** Lance version and the whole event-driven loop produces actual versioned data, not just
provenance.

This is the **same** ``read → transform → write → version`` contract a distributed Ray Data job
(``lance-ray`` on rask's KubeRay) fills in production; here it runs **in-process** so the cascade is
end-to-end testable without a Ray cluster. The transform is intentionally generic (carry the rows forward,
stamp a ``stage`` provenance column) — the realistic per-stage ML transform (embed / caption / aggregate)
is the distributed job's job at rask. Blocking Lance/S3 IO; callers run it in the threadpool.
"""

from __future__ import annotations

from typing import Any, cast

import lance
import pyarrow as pa
from pydantic import BaseModel

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


def _measure(uri: str, storage_options: dict[str, str]) -> WriteResult:
    """Read the just-written dataset's version + exact output statistics (rows + on-disk bytes)."""
    ds = lance.dataset(uri, storage_options=storage_options)
    # lance annotates ``DataStatistics.fields`` as a single ``FieldStatistics`` but returns a list at
    # runtime (upstream stub bug), so cast to the real shape before summing the per-field on-disk bytes.
    fields = cast("list[Any]", ds.stats.data_stats().fields)
    size_bytes = sum(field.bytes_on_disk for field in fields)
    return WriteResult(version=int(ds.version), row_count=ds.count_rows(), size_bytes=size_bytes)


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
    lance.write_dataset(
        table, uri, mode="overwrite", storage_options=storage_options, data_storage_version="2.2"
    )
    return _measure(uri, storage_options)


def transform_stage(
    from_uri: str, to_uri: str, storage_options: dict[str, str], *, stage: str
) -> WriteResult:
    """Read the upstream Lance dataset, stamp the ``stage`` provenance column, write the downstream dataset.

    The generic fake-Ray compute: real rows flow forward and the target version advances, so the cascade
    produces actual versioned data + lineage. ``stage`` is set (not appended twice) so re-running over an
    already-stamped upstream replaces the value rather than colliding on the column name. Returns the new
    downstream Lance version + the measured output statistics (rows + on-disk bytes) for the emit.
    """
    src = lance.dataset(from_uri, storage_options=storage_options).to_table()
    field = pa.field(_STAGE_COLUMN, pa.string())
    marker = pa.array([stage] * src.num_rows, pa.string())
    out = (
        src.set_column(src.schema.get_field_index(_STAGE_COLUMN), field, marker)
        if _STAGE_COLUMN in src.column_names
        else src.append_column(field, marker)
    )
    # 2.2 like seed_raw: every dataset the cascade writes is on the current format, so a future blob
    # column in any stage never trips "Blob v2 requires file version >= 2.2" mid-cascade.
    lance.write_dataset(
        out, to_uri, mode="overwrite", storage_options=storage_options, data_storage_version="2.2"
    )
    return _measure(to_uri, storage_options)
