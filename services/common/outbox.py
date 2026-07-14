"""Durable object-store outbox for lineage events (#4) — closes the commit→publish loss window.

Today a producer commits its Lance write and then does a FIRE-AND-FORGET Dapr publish (the sidecar accepts
the RPC but there is no broker/consumer ack). A crash between the commit and a durable delivery loses the
lineage event: the data landed but the graph never learns of it. The DLQ only catches events that were
published *then* failed delivery; the reconcile back-fill only recovers version+schema, not the full event.

The outbox closes it: the producer stages the FULL ``RunEvent`` JSON as an object under
``<outbox_uri>/<run_id>.json`` BEFORE the publish, and deletes it once the publish returns. Because the
stage happens AFTER the commit, every surviving object corresponds to a real committed write (no phantoms).
If the process crashes before the delete — or the publish never lands — the object survives and the lineage
service's reconcile relay re-ingests it (idempotent on ``run_id``) and deletes it. Strictly richer than the
version+schema back-fill: inputs, author, and columnLineage are all preserved.

Storage-agnostic: an ``s3://`` outbox uses an ``S3FileSystem`` built from the SAME ``storage_options`` the
producer/relay already use; a local/``file://`` path uses the local filesystem (dev + unit tests).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import suppress

import pyarrow.fs as pafs

log = logging.getLogger(__name__)

StorageOptions = dict[str, str]


def _fs_and_base(outbox_uri: str, storage_options: StorageOptions) -> tuple[pafs.FileSystem, str]:
    """Resolve ``(filesystem, base_path)`` for the outbox prefix. An ``s3://`` URI builds an S3FileSystem
    from the lance-style ``storage_options`` (endpoint/keys/region, path-style, http-ok); anything else
    (a ``file://`` or bare local path — dev/tests) resolves via the local filesystem."""
    if outbox_uri.startswith("s3://") and storage_options.get("endpoint"):
        scheme, _, host = storage_options["endpoint"].partition("://")
        fs = pafs.S3FileSystem(
            access_key=storage_options.get("access_key_id"),
            secret_key=storage_options.get("secret_access_key"),
            endpoint_override=host or storage_options["endpoint"],
            scheme=scheme or "http",
            region=storage_options.get("region", ""),
            allow_bucket_creation=True,
        )
        return fs, outbox_uri[len("s3://") :].rstrip("/")
    resolved, path = pafs.FileSystem.from_uri(outbox_uri)
    return resolved, path.rstrip("/")


def stage_event(outbox_uri: str, storage_options: StorageOptions, run_id: str, event_json: str) -> None:
    """Persist the event JSON at ``<outbox_uri>/<run_id>.json`` (overwrite — a redelivery re-stages the
    same run_id). Blocking object-store IO; callers run it in a threadpool."""
    fs, base = _fs_and_base(outbox_uri, storage_options)
    fs.create_dir(base, recursive=True)  # local FS needs the parent dir; an S3 prefix marker is harmless
    with fs.open_output_stream(f"{base}/{run_id}.json") as stream:
        stream.write(event_json.encode("utf-8"))


def drop_event(outbox_uri: str, storage_options: StorageOptions, run_id: str) -> None:
    """Delete the staged event (called after a publish returns / after the relay re-ingests it). An
    already-absent object is fine (idempotent). Blocking IO; callers threadpool it."""
    fs, base = _fs_and_base(outbox_uri, storage_options)
    with suppress(FileNotFoundError):
        fs.delete_file(f"{base}/{run_id}.json")


def list_events(outbox_uri: str, storage_options: StorageOptions) -> Iterator[tuple[str, str]]:
    """Yield ``(run_id, event_json)`` for every staged event under the outbox prefix (the relay's input).
    An absent prefix yields nothing. Blocking IO; the caller threadpools the whole drain."""
    fs, base = _fs_and_base(outbox_uri, storage_options)
    for info in fs.get_file_info(pafs.FileSelector(base, allow_not_found=True, recursive=False)):
        if info.type != pafs.FileType.File or not info.path.endswith(".json"):
            continue
        run_id = info.path.rsplit("/", 1)[-1].removesuffix(".json")
        # TOCTOU: the medallion mover stages-then-drops on this SAME prefix continuously, so an object
        # listed above can vanish before we open it. A concurrently-dropped event was already published
        # (that's why it's being dropped) — skip it, don't let the race 500 the whole reconcile tick.
        try:
            stream = fs.open_input_stream(info.path)
        except FileNotFoundError:
            continue
        with stream:
            yield run_id, stream.readall().decode("utf-8")


async def publish_lineage_with_outbox(
    publisher: object,
    *,
    outbox_uri: str,
    storage_options: StorageOptions,
    run_id: str,
    event_json: str,
    pubsub_name: str,
    topic_name: str,
    timeout_seconds: float,
) -> None:
    """Durably publish a lineage event: stage → publish → drop-on-ack (#4).

    With no ``outbox_uri`` configured this degrades to a plain publish (pre-#4 behavior), so the outbox is
    opt-in. A publish failure PROPAGATES (the producer's existing RETRY / redelivery handles it) and leaves
    the staged object in place, so even a hard process crash between the stage and a durable delivery is
    recoverable by the relay. The delete is best-effort: a failed delete just leaves a redundant object the
    relay re-ingests idempotently and drops.
    """
    from fastapi.concurrency import run_in_threadpool

    from common import dapr_publish

    staged = bool(outbox_uri)
    if staged:
        await run_in_threadpool(stage_event, outbox_uri, storage_options, run_id, event_json)
    await dapr_publish.publish_event(
        publisher,
        timeout_seconds=timeout_seconds,
        pubsub_name=pubsub_name,
        topic_name=topic_name,
        data=event_json,
        data_content_type="application/json",
    )
    if staged:
        with suppress(Exception):
            await run_in_threadpool(drop_event, outbox_uri, storage_options, run_id)
