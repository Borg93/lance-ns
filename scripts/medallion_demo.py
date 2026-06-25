"""Live medallion demo driver — real Lance data on S3 + real OpenLineage to the lineage service.

Unlike ``lineage/seed.py`` (which emits *synthetic* events only), this **executes** the medallion
flow against the real docker-compose services: it writes and evolves real Lance datasets on MinIO
*and* emits a real OpenLineage event after each step, with a pause in between, so the thin frontend
(``lineage/static/index.html``, served at ``/ui/``) shows the DAG build and the silver versions
evolve live.

The flow (faithful to ``lineage/seed.py`` / ``docs/LINEAGE.md``):

    ingest_events    (alice)    raw_events      -> bronze$events  v1  (blob payload)
    embed_features   (data_eng) bronze$events   x  silver$features     (FAILS — recorded, no data)
    embed_features   (data_eng) bronze$events   -> silver$features v1  (+embedding)
    caption_features (data_eng) silver$features -> silver$features v2  (+caption, in place)
    aggregate_gold   (analyst)  silver$features -> gold$catalog    v1  (+lineage JSONB)

The object store is **RustFS** (Rust, S3-compatible) by default — the driver is storage-agnostic
(it only speaks S3 ``storage_options``), so MinIO/Ceph/AWS work identically by changing the creds.

Run (after ``scripts/medallion_demo.sh`` brings up RustFS + lineage)::

    uv run scripts/medallion_demo.py

Env (defaults target the RustFS compose stack from the host)::

    S3_ENDPOINT=http://localhost:9000  S3_ACCESS_KEY=rustfsadmin  S3_SECRET_KEY=rustfsadmin
    S3_REGION=us-east-1  S3_BUCKET=lakehouse  LINEAGE_URL=http://localhost:8000  STEP_DELAY=2.5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import lance
import pyarrow as pa
import pyarrow.fs as pafs
from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import RunEvent, RunState
from openlineage.client.transport.http import HttpConfig, HttpTransport

# Make the repo-root ``lineage`` package importable when run as a plain script
# (python puts scripts/ on sys.path, not the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage.seed import build_events  # noqa: E402  (intentional: after the sys.path bootstrap)

try:
    from lance import blob_array, blob_field

    _HAVE_BLOB = True
except ImportError:  # pragma: no cover - depends on the installed lance build
    _HAVE_BLOB = False


def _load_demo_env() -> None:
    """Load demo endpoints from ``<repo>/.medallion-demo.env`` (written when the stack starts), so a
    bare ``--step N`` targets the *actual* ports without an env-var prefix. Real env vars win."""
    path = Path(__file__).resolve().parent.parent / ".medallion-demo.env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_demo_env()

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
S3_KEY = os.environ.get("S3_ACCESS_KEY", "rustfsadmin")
S3_SECRET = os.environ.get("S3_SECRET_KEY", "rustfsadmin")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "lakehouse")
LINEAGE_URL = os.environ.get("LINEAGE_URL", "http://localhost:8000").rstrip("/")
STEP_DELAY = float(os.environ.get("STEP_DELAY", "2.5"))

_BRONZE = f"s3://{S3_BUCKET}/bronze/events"
_SILVER = f"s3://{S3_BUCKET}/silver/features"
_GOLD = f"s3://{S3_BUCKET}/gold/catalog"


def _say(message: str) -> None:
    print(f"  ▸ {message}", flush=True)


def _storage_options() -> dict[str, str]:
    """The pylance ``storage_options`` for the demo S3 backend (same keys the catalog uses)."""
    return {
        "endpoint": S3_ENDPOINT,
        "access_key_id": S3_KEY,
        "secret_access_key": S3_SECRET,
        "region": S3_REGION,
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
    }


def _s3_filesystem() -> pafs.S3FileSystem:
    scheme, _, host = S3_ENDPOINT.partition("://")
    return pafs.S3FileSystem(
        access_key=S3_KEY,
        secret_key=S3_SECRET,
        endpoint_override=host or scheme,
        scheme=scheme if host else "http",
        region=S3_REGION,
        allow_bucket_creation=True,
    )


def ensure_bucket() -> None:
    """Create the demo bucket if it doesn't exist (object stores never auto-create buckets)."""
    try:
        _s3_filesystem().create_dir(S3_BUCKET)  # allow_bucket_creation makes this the bucket
        _say(f"bucket s3://{S3_BUCKET} ready")
    except Exception as exc:  # noqa: BLE001 - bucket may already exist; that's fine
        _say(f"bucket s3://{S3_BUCKET} (already present or: {exc})")


def reset_data() -> None:
    """Delete the demo's Lance datasets from S3 — a clean slate before re-running the flow."""
    fs = _s3_filesystem()
    for layer in ("bronze", "silver", "gold"):
        path = f"{S3_BUCKET}/{layer}"
        try:
            fs.delete_dir(path)
            _say(f"deleted s3://{path}")
        except Exception:  # noqa: BLE001 - absent is fine (nothing written there yet)
            _say(f"s3://{path} (nothing to delete)")


def write_bronze() -> None:
    """alice's ETL: land raw events into bronze with a multimodal blob ``payload`` column."""
    opts = _storage_options()
    ids = [1, 2, 3]
    payloads = [f"<bytes for event {i}>".encode() for i in ids]
    srcs = ["cam-a", "cam-b", "cam-a"]
    if _HAVE_BLOB:
        schema = pa.schema(
            [pa.field("id", pa.int64()), blob_field("payload"), pa.field("src", pa.string())]
        )
        table = pa.table({"id": ids, "payload": blob_array(payloads), "src": srcs}, schema=schema)
        lance.write_dataset(
            table, _BRONZE, storage_options=opts, mode="overwrite", data_storage_version="2.2"
        )
    else:  # fall back to a plain binary column if blob v2 isn't available in this build
        table = pa.table({"id": ids, "payload": payloads, "src": srcs})
        lance.write_dataset(table, _BRONZE, storage_options=opts, mode="overwrite")
    _say(f"bronze$events written ({len(ids)} rows, blob payload) -> {_BRONZE}")


def write_silver() -> None:
    """data_eng's embed: read bronze, add an ``embedding`` column, write silver v1."""
    opts = _storage_options()
    src = lance.dataset(_BRONZE, storage_options=opts).to_table(columns=["id", "src"])
    ids = src.column("id").to_pylist()
    embedding = pa.array(
        [[float((i + j) % 7) / 7.0 for j in range(8)] for i in ids], type=pa.list_(pa.float32(), 8)
    )
    table = pa.table({"id": src.column("id"), "src": src.column("src"), "embedding": embedding})
    lance.write_dataset(table, _SILVER, storage_options=opts, mode="overwrite")
    _say(f"silver$features v1 written ({len(ids)} rows, +embedding) -> {_SILVER}")


def add_caption() -> None:
    """data_eng's refine: add a ``caption`` column in place (Lance data evolution -> version bump)."""
    ds = lance.dataset(_SILVER, storage_options=_storage_options())
    ds.add_columns({"caption": "'auto-caption'"})
    _say("silver$features v2 written (+caption, in-place add-column)")


def write_gold() -> None:
    """analyst's aggregate: write gold and embed the upstream provenance as a JSONB ``lineage`` column."""
    opts = _storage_options()
    sv = lance.dataset(_SILVER, storage_options=opts).to_table()
    provenance = {
        "dataset": "gold$catalog",
        "produced_by": "aggregate_gold",
        "author": "analyst",
        "upstream": [
            {"name": "silver$features", "version": 2},
            {"name": "bronze$events", "version": 1},
            {"name": "raw_events"},
        ],
    }
    lineage_json = [json.dumps(provenance)] * sv.num_rows
    try:
        lineage_col = pa.array(lineage_json, type=pa.json_())
    except (pa.ArrowNotImplementedError, TypeError):  # pragma: no cover - older arrow/lance build
        lineage_col = pa.array(lineage_json, type=pa.string())
    table = pa.table(
        {"caption": sv.column("caption"), "embedding": sv.column("embedding"), "lineage": lineage_col}
    )
    lance.write_dataset(table, _GOLD, storage_options=opts, mode="overwrite")
    _say(f"gold$catalog v1 written ({sv.num_rows} rows, +lineage JSONB) -> {_GOLD}")


def _perform(event: RunEvent) -> None:
    """Run the real Lance operation that corresponds to one OpenLineage event."""
    if event.eventType == RunState.FAIL:
        _say("embed_features attempt FAILED (simulated CUDA OOM) — recorded, no data written")
        return
    {
        "ingest_events": write_bronze,
        "embed_features": write_silver,
        "caption_features": add_caption,
        "aggregate_gold": write_gold,
    }[event.job.name]()


def _describe(event: RunEvent) -> str:
    state = "FAIL" if event.eventType == RunState.FAIL else "COMPLETE"
    out = event.outputs[0].name if event.outputs else "-"
    src = event.inputs[0].name if event.inputs else "-"
    return f"{event.job.name:16} {state:8} {src} -> {out}"


def _emit_step(client: OpenLineageClient, index: int, total: int, event: RunEvent, *, data: bool) -> None:
    """Perform the real Lance op (unless ``data`` is False) and emit the OpenLineage event."""
    state = "FAIL" if event.eventType == RunState.FAIL else "COMPLETE"
    print(f"\n[{index}/{total}] {_describe(event)}")
    if data:
        _perform(event)
    client.emit(event)
    _say(f"OpenLineage {state} emitted → {LINEAGE_URL}/api/v1/lineage")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive the live medallion flow (data + OpenLineage).")
    parser.add_argument("--step", type=int, metavar="N", help="emit ONLY step N (you are the producer)")
    parser.add_argument("--list", action="store_true", help="list the steps and exit (no side effects)")
    parser.add_argument("--reset", action="store_true", help="delete the demo's Lance datasets and exit")
    parser.add_argument(
        "--emit-only", action="store_true", help="emit the OpenLineage event(s) only, skip the Lance data op"
    )
    parser.add_argument("--delay", type=float, default=STEP_DELAY, help="seconds between steps in auto mode")
    args = parser.parse_args()

    events = build_events()
    if args.list:
        print("\nMedallion steps (use --step N to trigger one manually):\n")
        for i, event in enumerate(events, start=1):
            print(f"  {i}. {_describe(event)}")
        print(f"\nWatch the graph build at {LINEAGE_URL}/ui/\n")
        return

    if args.reset:
        print(f"\nReset → clearing the demo's Lance datasets under s3://{S3_BUCKET}\n")
        reset_data()
        return

    do_data = not args.emit_only
    print(f"\nLive medallion → S3 {S3_ENDPOINT} (bucket {S3_BUCKET}) + lineage {LINEAGE_URL}\n")
    if do_data:
        ensure_bucket()
    # HttpTransport appends its default endpoint (api/v1/lineage) to the base url, so pass the base.
    client = OpenLineageClient(transport=HttpTransport(HttpConfig(url=LINEAGE_URL)))

    if args.step is not None:
        if not 1 <= args.step <= len(events):
            parser.error(f"--step must be between 1 and {len(events)}")
        _emit_step(client, args.step, len(events), events[args.step - 1], data=do_data)
        nxt = min(args.step + 1, len(events))
        print(f"\n✓ step {args.step} done. Graph: {LINEAGE_URL}/ui/  ·  next: --step {nxt}\n")
        return

    for index, event in enumerate(events, start=1):
        _emit_step(client, index, len(events), event, data=do_data)
        time.sleep(args.delay)
    print(f"\n✓ done. Watch the lineage graph build at {LINEAGE_URL}/ui/\n")


if __name__ == "__main__":
    main()
