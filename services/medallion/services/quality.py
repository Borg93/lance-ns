"""Automated data-quality assertions for the medallion quality gate.

A medallion stage that produced a real Lance dataset (compute on) can be VALIDATED before it promotes: the
mover runs cheap, exact assertions on the dataset it just wrote — does it have rows? is the key column free
of nulls? — and emits them as the standard OpenLineage ``dataQualityAssertions`` facet. When the quality
GATE is enabled, a failed assertion BLOCKS promotion: the failed run is still recorded (lineage keeps the
assertions, so the bad batch is auditable) but the next stage is never triggered, so bad data can't cascade.

This is the automated *validator* half of governance, and it composes with the FGA gate: FGA decides who
MAY promote (a registered identity holding the role); quality decides whether the DATA is good enough to.
Both gate movement. The checks use ``count_rows`` (with a filter) so they never materialise the table.
"""

from __future__ import annotations

import logging

import lance
from common import blobs
from pydantic import BaseModel

log = logging.getLogger(__name__)

#: Assertion names — stable identifiers the ``dataQualityAssertions`` facet carries (and the gate keys on).
ROW_COUNT_POSITIVE = "row_count_positive"
NOT_NULL = "not_null"
BLOB_RESOLVES = "blob_resolves"


class Assertion(BaseModel):
    """One data-quality check on a produced dataset (the OpenLineage ``dataQualityAssertions`` shape)."""

    assertion: str
    success: bool
    column: str | None = None


def assert_quality(uri: str, storage_options: dict[str, str], *, key_column: str) -> list[Assertion]:
    """Run cheap, exact quality assertions on the just-written Lance dataset at ``uri``.

    - ``row_count_positive``: the dataset has at least one row (an empty promotion is a silent failure).
    - ``not_null`` on ``key_column``: the identity column has no nulls (a broken join/transform). Skipped
      (not failed) when the stage's data doesn't carry that column — different stages may key differently.
    - ``blob_resolves`` per blob-v2 column (§9 P2): the blob POINTERS actually dereference to bytes.
      A blob column can pass every tabular check while its payloads are gone — an external
      ``Blob.from_uri`` object deleted from under the table (the bucket-wipe case) fails only when
      someone finally reads it, far downstream of the promotion that let it through. Skipped (not
      failed) when the dataset has no blob column.

    The tabular checks use ``count_rows`` (with a filter for the null check) so the table is never
    materialised; the blob check reads ONE byte from the first and last rows' payloads per column.
    """
    ds = lance.dataset(uri, storage_options=storage_options)
    assertions = [Assertion(assertion=ROW_COUNT_POSITIVE, success=ds.count_rows() > 0)]
    if key_column and key_column in ds.schema.names:
        nulls = ds.count_rows(f"{key_column} IS NULL")
        assertions.append(Assertion(assertion=NOT_NULL, success=nulls == 0, column=key_column))
    for column in blobs.blob_field_names(ds.schema):
        assertions.append(
            Assertion(assertion=BLOB_RESOLVES, success=_blob_resolves(ds, column), column=column)
        )
    return assertions


def _blob_resolves(ds: lance.LanceDataset, column: str) -> bool:
    """Whether ``column``'s blob payloads dereference — probed on the FIRST and LAST rows only.

    One real byte is read per probed payload: ``BlobFile.size()`` reads only the stored descriptor
    (probed at pylance 8.0.0 — it succeeds against a deleted object), so only an actual
    ``read_range`` proves the bytes are reachable; and for a dangling EXTERNAL pointer even
    ``take_blobs`` itself raises (it opens the object), which is why the whole probe sits in the
    try. First+last catches the wholesale failures the gate exists for (wiped bucket, wrong or
    unregistered external base) at the cost of two 1-byte reads; per-row bitrot auditing is a
    scrubber's job, not a promotion gate's. Zero-length/null payloads resolve trivially
    (``take_blobs`` returns no handle for them — same probed behavior the serving path guards).
    """
    rows = ds.count_rows()
    if rows == 0:
        return True  # nothing to resolve; row_count_positive already fails the gate
    try:
        for row in sorted({0, rows - 1}):
            for handle in ds.take_blobs(column, indices=[row]):
                if handle.size() > 0:
                    handle.read_range(0, 1)
    except Exception as exc:  # noqa: BLE001 — ANY resolve failure is exactly what this assertion reports
        log.warning("blob_resolve_failed", extra={"column": column, "error": str(exc)})
        return False
    return True


def passed(assertions: list[Assertion]) -> bool:
    """Whether EVERY assertion succeeded — the gate promotes only when this is true."""
    return all(a.success for a in assertions)
