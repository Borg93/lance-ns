"""Ray Data stage-transform job for the EVENT-DRIVEN medallion cascade.

A medallion mover submits this via the Ray Jobs REST API (services/medallion/services/ray_submit.py) IN
RESPONSE TO its Dapr cascade trigger — the production-shape replacement for the in-process fake-Ray
``compute.transform_stage``. It reads the upstream Lance dataset, stamps a ``stage`` provenance column across
Ray workers, and writes the downstream dataset at file format 2.2 with stable row ids (create the target with
stable ids, then distributed-append — lance_ray.write_lance has no stable-row-ids param). The mover then reads
the written version + statistics for the OpenLineage WROTE edge, exactly as the in-process path does.

TWO paths, chosen by whether the upstream carries a blob-v2 column:
* TABULAR → the distributed lance_ray read→map_batches(stamp)→write path (Ray workers, one commit).
* MEDIA (blob-v2 present) → a pylance-native round-trip on the driver: lance_ray's write strips blob
  typing (exposes plain LargeBinary), so a blob column must be re-materialised via ``read_blobs`` and
  re-wrapped with ``blob_array`` before a 2.2 write, and image payloads get an inline thumbnail +
  embedding derived here. This is the SAME contract as compute.transform_stage / derivers — the deriver
  is inlined (self-contained job, like ray_train_job) and drift-pinned to services/medallion by a unit
  test. Closes the Phase-3 gap that forced media stages onto the in-process fallback (Ray blob parity).

Env: FROM_URI TO_URI STAGE  S3_ENDPOINT S3_KEY S3_SECRET [S3_REGION].
"""

from __future__ import annotations

import contextlib
import io
import os
import warnings

import lance
import pyarrow as pa
import pyarrow.fs as pafs
from lance import blob_array, blob_field

# lance_ray ships in the Ray image, NOT our services' venv — imported LAZILY (inside the tabular branch
# of main) so the deriver primitives below stay importable in the unit venv for the drift-pin test
# (tests/unit/test_ray_stage_job.py), exactly as ray_train_job keeps `lance` out of its module top.

# --- blob + deriver primitives, inlined + drift-pinned to services (test_ray_stage_job.py) --------------
# Kept byte-identical to common.blobs.is_blob_field / medallion.services.media so the Ray path and the
# in-process path derive the SAME thumbnail/embedding; the pin test fails if either side drifts.
_BLOB_V2_EXTENSION_NAME = "lance.blob.v2"  # == common.blobs.BLOB_V2_EXTENSION_NAME
_THUMBNAIL_SIZE = (128, 128)  # == media.THUMBNAIL_SIZE
_EMBEDDING_DIMS = 8  # == media.EMBEDDING_DIMS


def _is_blob_field(field: pa.Field) -> bool:
    """Mirror of common.blobs.is_blob_field: registered extension name, else the raw field metadata."""
    if getattr(field.type, "extension_name", None) == _BLOB_V2_EXTENSION_NAME:
        return True
    metadata = field.metadata or {}
    return metadata.get(b"ARROW:extension:name") == _BLOB_V2_EXTENSION_NAME.encode()


def _blob_field_names(schema: pa.Schema) -> list[str]:
    return [f.name for f in schema if _is_blob_field(f)]


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


def _open_guarded(payload: bytes):  # -> PIL.Image.Image
    """Mirror of media._open_guarded: decompression-bomb-guarded open (Pillow default only trips at 2×)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 64_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        return Image.open(io.BytesIO(payload))


def _derive_thumbnail(image_bytes: bytes) -> bytes:
    """Mirror of media.derive_thumbnail: a downscaled inline PNG thumbnail."""
    from PIL import Image  # noqa: F401 — ensures the guarded open above ran Image config

    with _open_guarded(image_bytes) as image:
        thumb = image.convert("RGB")
        thumb.thumbnail(_THUMBNAIL_SIZE)
        buffer = io.BytesIO()
        thumb.save(buffer, format="PNG")
        return buffer.getvalue()


def _derive_embedding(image_bytes: bytes) -> list[float]:
    """Mirror of media.derive_embedding: deterministic luminance downsample to _EMBEDDING_DIMS floats."""
    from PIL import Image

    with _open_guarded(image_bytes) as image:
        columns = image.convert("L").resize((_EMBEDDING_DIMS, 1), resample=Image.Resampling.BILINEAR)
        return [value / 255.0 for value in columns.tobytes()]


def _is_image(payload: bytes) -> bool:
    """Mirror of media.is_image: decode-probe the payload (verify headers, any failure → not an image)."""
    try:
        with _open_guarded(payload) as image:
            image.verify()
    except Exception:  # noqa: BLE001 — a decode failure means "not an image", never an error
        return False
    return True


def _media_transform(from_uri: str, to_uri: str, so: dict[str, str], *, stage: str) -> None:
    """The MEDIA path: pylance-native blob round-trip + inline image derivation, then a 2.2 stable-id write.

    Same contract as compute.transform_stage + derivers.derive_artifacts: re-materialise each blob column
    via ``read_blobs`` and re-wrap with ``blob_array`` (lance_ray's write would demote it to plain binary),
    stamp ``stage``, and for a blob column whose FIRST payload decodes as an image, append an inline
    ``thumbnail`` (PNG) + ``embedding`` (fixed-size floats). Non-image blobs carry through untouched.
    """
    ds = lance.dataset(from_uri, storage_options=so)
    blob_cols = _blob_field_names(ds.schema)
    rows = ds.count_rows()
    plain = ds.to_table(columns=[f.name for f in ds.schema if f.name not in blob_cols and f.name != "stage"])

    columns: dict = {}
    fields: list[pa.Field] = []
    first_payloads: dict[str, list[bytes]] = {}
    for f in ds.schema:
        if f.name == "stage":
            continue  # re-stamped below
        if f.name in blob_cols:
            payloads = [payload for _addr, payload in ds.read_blobs(f.name, indices=list(range(rows)))]
            first_payloads[f.name] = payloads
            fields.append(blob_field(f.name))
            columns[f.name] = blob_array(payloads)
        else:
            fields.append(plain.schema.field(f.name))
            columns[f.name] = plain.column(f.name)
    fields.append(pa.field("stage", pa.string()))
    columns["stage"] = pa.array([stage] * rows, pa.string())
    out = pa.table(columns, schema=pa.schema(fields))

    # Derive from the first IMAGE blob column (the media lane has exactly one: `payload`). Row-wise, image
    # payloads only — a payload past the header probe that fails full decode raises, FAILing the run.
    for payloads in first_payloads.values():
        if payloads and _is_image(payloads[0]):
            thumbnails = [_derive_thumbnail(p) for p in payloads]
            embeddings = [_derive_embedding(p) for p in payloads]
            out = out.append_column(
                pa.field("thumbnail", pa.large_binary()), pa.array(thumbnails, pa.large_binary())
            )
            out = out.append_column(
                pa.field("embedding", pa.list_(pa.float32(), _EMBEDDING_DIMS)),
                pa.array(embeddings, type=pa.list_(pa.float32(), _EMBEDDING_DIMS)),
            )
            break  # one media column per stage (matches derivers._DERIVERS' first-match contract)

    # Same overwrite contract as the in-process compute.transform_stage: enable_stable_row_ids is
    # create-time-only, so a first write creates the target with stable ids and later runs overwrite in
    # place keeping them. A legacy no-stable-id target is migrated once (the tabular path's reset); the
    # media lane's silver dataset is always created BY this contract, so no reset is needed here.
    lance.write_dataset(
        out,
        to_uri,
        mode="overwrite",
        storage_options=so,
        data_storage_version="2.2",
        enable_stable_row_ids=True,
    )


def main() -> None:
    so = _storage_options()
    from_uri, to_uri, stage = os.environ["FROM_URI"], os.environ["TO_URI"], os.environ["STAGE"]

    upstream = lance.dataset(from_uri, storage_options=so)

    if _blob_field_names(upstream.schema):
        # MEDIA path: lance_ray strips blob typing on write, so round-trip + derive via pylance (below).
        _media_transform(from_uri, to_uri, so, stage=stage)
    else:
        base = upstream.schema
        if "stage" in base.names:
            base = base.remove(base.get_field_index("stage"))
        out_schema = base.append(pa.field("stage", pa.string()))

        import lance_ray as lr  # ty: ignore[unresolved-import]  # Ray-image only; lazy (see module top)

        # Distributed transform on Ray, then a stable-row-id write: create dst with stable ids (empty, output
        # schema) and distributed-APPEND the Ray fragments into it (the property is dataset-level, so they
        # inherit it). concurrency>1 → fragments written in parallel + one commit.
        transformed = lr.read_lance(from_uri, storage_options=so).map_batches(
            lambda table: _stamp_stage(table, stage), batch_format="pyarrow"
        )
        # Clear ONLY when a legacy dataset (created without stable ids) exists — enable_stable_row_ids is
        # create-time-only, so overwrite alone won't flip it; a dataset that already has stable ids keeps
        # them under overwrite, so the raw dir-wipe (+ its concurrency hazard) is a one-time migration.
        needs_reset = False
        with contextlib.suppress(Exception):
            needs_reset = not lance.dataset(to_uri, storage_options=so).has_stable_row_ids
        if needs_reset:
            _reset_dataset(to_uri, so)
        lance.write_dataset(
            out_schema.empty_table(),
            to_uri,
            storage_options=so,
            mode="overwrite",
            data_storage_version="2.2",
            enable_stable_row_ids=True,
        )
        lr.write_lance(
            transformed,
            to_uri,
            storage_options=so,
            mode="append",
            data_storage_version="2.2",
            concurrency=2,
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
