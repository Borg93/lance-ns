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

import lance
import pyarrow as pa

_STAGE_COLUMN = "stage"


def _version(uri: str, storage_options: dict[str, str]) -> int:
    """The current Lance version of the dataset at ``uri`` (what the emitted lineage records)."""
    return int(lance.dataset(uri, storage_options=storage_options).version)


def seed_raw(uri: str, storage_options: dict[str, str], *, rows: int = 8) -> int:
    """Seed a small synthetic ``raw_events`` dataset — the fake lance-ray ingest at the head of the cascade.

    Overwrites any existing dataset (idempotent re-seed) and returns the resulting Lance version.
    """
    table = pa.table(
        {
            "id": pa.array(list(range(rows)), pa.int64()),
            "payload": pa.array([f"event-{i}" for i in range(rows)]),
        }
    )
    lance.write_dataset(table, uri, mode="overwrite", storage_options=storage_options)
    return _version(uri, storage_options)


def transform_stage(from_uri: str, to_uri: str, storage_options: dict[str, str], *, stage: str) -> int:
    """Read the upstream Lance dataset, stamp the ``stage`` provenance column, write the downstream dataset.

    The generic fake-Ray compute: real rows flow forward and the target version advances, so the cascade
    produces actual versioned data + lineage. ``stage`` is set (not appended twice) so re-running over an
    already-stamped upstream replaces the value rather than colliding on the column name. Returns the new
    downstream Lance version.
    """
    src = lance.dataset(from_uri, storage_options=storage_options).to_table()
    field = pa.field(_STAGE_COLUMN, pa.string())
    marker = pa.array([stage] * src.num_rows, pa.string())
    out = (
        src.set_column(src.schema.get_field_index(_STAGE_COLUMN), field, marker)
        if _STAGE_COLUMN in src.column_names
        else src.append_column(field, marker)
    )
    lance.write_dataset(out, to_uri, mode="overwrite", storage_options=storage_options)
    return _version(to_uri, storage_options)
