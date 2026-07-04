"""Ray Data stage-transform job for the EVENT-DRIVEN medallion cascade.

A medallion mover submits this via the Ray Jobs REST API (services/medallion/services/ray_submit.py) IN
RESPONSE TO its Dapr cascade trigger — the production-shape replacement for the in-process fake-Ray
``compute.transform_stage``. It reads the upstream Lance dataset, stamps a ``stage`` provenance column across
Ray workers, and writes the downstream dataset at file format 2.2 with stable row ids (create the target with
stable ids, then distributed-append — lance_ray.write_lance has no stable-row-ids param). The mover then reads
the written version + statistics for the OpenLineage WROTE edge, exactly as the in-process path does.

Env: FROM_URI TO_URI STAGE  S3_ENDPOINT S3_KEY S3_SECRET [S3_REGION].
"""

from __future__ import annotations

import contextlib
import os

import lance
import lance_ray as lr  # ty: ignore[unresolved-import]  # ships in the Ray image, not our services' venv
import pyarrow as pa
import pyarrow.fs as pafs


def _storage_options() -> dict[str, str]:
    return {
        "endpoint": os.environ["S3_ENDPOINT"],
        "access_key_id": os.environ["S3_KEY"],
        "secret_access_key": os.environ["S3_SECRET"],
        "region": os.environ.get("S3_REGION", "us-east-1"),
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
    }


def _reset_dataset(to_uri: str, so: dict[str, str]) -> None:
    """Delete any existing dataset at ``to_uri`` so the create-with-stable-ids below is truly fresh.

    ``enable_stable_row_ids`` is a create-time-only property: ``mode="overwrite"`` on a dataset that already
    exists WITHOUT stable ids (e.g. one a prior in-process run created) does NOT flip it on. The cascade uses
    overwrite semantics (each run's output IS the whole dataset), so clearing the dir first is correct here.
    """
    endpoint = so["endpoint"]
    scheme, _, host = endpoint.partition("://")
    fs = pafs.S3FileSystem(
        endpoint_override=host or endpoint,
        access_key=so["access_key_id"],
        secret_key=so["secret_access_key"],
        region=so.get("region", "us-east-1"),
        scheme=scheme if host else "http",
    )
    with contextlib.suppress(OSError):
        fs.delete_dir_contents(to_uri.removeprefix("s3://"), missing_dir_ok=True)


def _stamp_stage(table: pa.Table, stage: str) -> pa.Table:
    """Carry every upstream column forward and (re)stamp the ``stage`` provenance column — the generic
    per-stage transform, type-preserving via the pyarrow batch format."""
    if "stage" in table.column_names:
        table = table.drop_columns(["stage"])
    return table.append_column("stage", pa.array([stage] * table.num_rows, pa.string()))


def main() -> None:
    so = _storage_options()
    from_uri, to_uri, stage = os.environ["FROM_URI"], os.environ["TO_URI"], os.environ["STAGE"]

    upstream = lance.dataset(from_uri, storage_options=so)
    base = upstream.schema
    if "stage" in base.names:
        base = base.remove(base.get_field_index("stage"))
    out_schema = base.append(pa.field("stage", pa.string()))

    # Distributed transform on Ray, then a stable-row-id write: create dst with stable ids (empty, output
    # schema) and distributed-APPEND the Ray fragments into it (the property is dataset-level, so they inherit
    # it). concurrency>1 → fragments written in parallel + one commit.
    transformed = lr.read_lance(from_uri, storage_options=so).map_batches(
        lambda table: _stamp_stage(table, stage), batch_format="pyarrow"
    )
    # Clear ONLY when a legacy dataset (created without stable ids) exists — enable_stable_row_ids is
    # create-time-only, so overwrite alone won't flip it; a dataset that already has stable ids keeps them
    # under overwrite, so the raw dir-wipe (and its concurrency hazard) is confined to a one-time migration.
    needs_reset = False
    with contextlib.suppress(Exception):
        needs_reset = not lance.dataset(to_uri, storage_options=so).has_stable_row_ids
    if needs_reset:
        _reset_dataset(to_uri, so)
    lance.write_dataset(
        out_schema.empty_table(), to_uri, storage_options=so, mode="overwrite",
        data_storage_version="2.2", enable_stable_row_ids=True,
    )
    lr.write_lance(
        transformed, to_uri, storage_options=so, mode="append",
        data_storage_version="2.2", concurrency=2,
    )

    out = lance.dataset(to_uri, storage_options=so)
    print(
        f"RAY-STAGE OK stage={stage} rows={out.count_rows()} version={out.version} "
        f"dsv={out.data_storage_version} stable_row_ids={out.has_stable_row_ids} cols={out.schema.names}"
    )
    if out.count_rows() != upstream.count_rows() or not out.has_stable_row_ids:
        raise SystemExit("stage transform produced wrong row count or lost stable row ids")


if __name__ == "__main__":
    main()
