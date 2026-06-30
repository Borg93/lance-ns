"""Compaction service — a FastAPI app triggered by a Dapr cron **input binding**.

A ``bindings.cron`` component POSTs to ``/<binding-name>`` every interval (no app code drives the
schedule — it's component config). Each tick runs one maintenance sweep: discover every Lance dataset in
the lakehouse bucket, then ``compact_files()`` + ``cleanup_old_versions()`` each. Blocking Lance/S3 IO
runs in the threadpool so the event loop stays free. Run: ``uvicorn compaction.service:app``.

Thin entrypoint: lifespan + ``FastAPI()`` + health, with the cron route + OPTIONS ack registered via
``compaction.api.routes``. The sweep logic lives in ``compaction.services``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from compaction.api.routes import router
from compaction.core.config import apply_dapr_secrets, get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Consume the S3 secret from the Dapr secret store (OpenBao) before the first cron sweep, so the
    # sweep's S3 access uses a store-sourced key and the plaintext secret never ships in pod env — the
    # audit's secret-consumption fix. Mutates the cached settings in place; fails closed if unavailable.
    apply_dapr_secrets(get_settings())
    yield


app = FastAPI(title="Lance compaction/GC", version="0.1.0", lifespan=lifespan)


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


# The Dapr cron route (POST /<binding-name>) + its OPTIONS discovery ack, with the require_dapr_token gate.
app.include_router(router)
