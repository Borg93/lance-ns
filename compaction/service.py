"""Compaction service — a FastAPI app triggered by a Dapr cron **input binding**.

A ``bindings.cron`` component POSTs to ``/<binding-name>`` every interval (no app code drives the
schedule — it's component config). Each tick runs one maintenance sweep: discover every Lance dataset in
the lakehouse bucket, then ``compact_files()`` + ``cleanup_old_versions()`` each. Blocking Lance/S3 IO
runs in the threadpool so the event loop stays free. Run: ``uvicorn compaction.service:app``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pyarrow.fs as pafs
from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool

from app.core.dapr_auth import require_dapr_token
from compaction.config import CompactionSettings, apply_dapr_secrets, get_settings
from compaction.metrics import record_reclaimed, record_run
from compaction.optimize import DatasetResult, compact_one, discover_dataset_uris

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Consume the S3 secret from the Dapr secret store (OpenBao) before the first cron sweep, so the
    # sweep's S3 access uses a store-sourced key and the plaintext secret never ships in pod env — the
    # audit's secret-consumption fix. Mutates the cached settings in place; fails closed if unavailable.
    apply_dapr_secrets(get_settings())
    yield


app = FastAPI(title="Lance compaction/GC", version="0.1.0", lifespan=lifespan)
_settings = get_settings()


def _s3fs(settings: CompactionSettings) -> pafs.S3FileSystem:
    """A pyarrow S3 filesystem over the (dev, HTTP) RustFS endpoint — used only to LIST the bucket."""
    endpoint = settings.s3_endpoint.removeprefix("http://").removeprefix("https://")
    return pafs.S3FileSystem(
        endpoint_override=endpoint,
        access_key=settings.s3_access_key_id,
        secret_key=settings.s3_secret_access_key,
        scheme="http",
        region=settings.s3_region,
    )


def run_sweep(settings: CompactionSettings) -> list[DatasetResult]:
    """Discover every dataset in the bucket and compact + GC each; record what the sweep reclaimed."""
    older_than = timedelta(days=settings.older_than_days)
    options = settings.storage_options()
    uris = discover_dataset_uris(_s3fs(settings), settings.s3_bucket)
    results = [compact_one(uri, options, older_than) for uri in uris]
    record_run()
    record_reclaimed(
        fragments_removed=sum(r.fragments_removed for r in results),
        versions_removed=sum(r.old_versions_removed for r in results),
        indices_optimized=sum(r.indices_optimized for r in results),
    )
    return results


def summarize(results: list[DatasetResult]) -> dict[str, Any]:
    """Aggregate one sweep's per-dataset results into the cron response. Failures keep their MESSAGE
    (not just the URI) — a cron sweep has no human watching, so the *why* is the only debugging signal."""
    return {
        "datasets": len(results),
        "fragments_removed": sum(r.fragments_removed for r in results),
        "indices_optimized": sum(r.indices_optimized for r in results),
        "versions_removed": sum(r.old_versions_removed for r in results),
        "errors": {r.uri: r.error for r in results if r.error},
    }


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


async def on_cron() -> dict[str, Any]:
    """One maintenance sweep, triggered by a Dapr cron tick (POST /<binding-name>)."""
    summary = summarize(await run_in_threadpool(run_sweep, get_settings()))
    log.info("compaction_sweep", extra=summary)
    return summary


async def ack_binding() -> dict[str, str]:
    """Dapr's startup pre-flight (OPTIONS /<binding-name>) — a 2xx confirms this app consumes the binding."""
    return {"status": "ok"}


# Register the cron route at the exact binding name the sidecar delivers to: POST runs the sweep, OPTIONS
# acks Dapr's binding-discovery pre-flight (else it 405s and Dapr logs the app as not consuming it).
app.add_api_route(
    f"/{_settings.binding_name}",
    on_cron,
    methods=["POST"],
    tags=["compaction"],
    dependencies=[Depends(require_dapr_token)],  # only the sidecar's cron tick may trigger a sweep
)
app.add_api_route(f"/{_settings.binding_name}", ack_binding, methods=["OPTIONS"], include_in_schema=False)
