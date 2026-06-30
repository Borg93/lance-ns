"""A medallion stage mover — one DAG edge, event-driven (FastAPI application entry).

All three movers run THIS module (``medallion.mover:app``) and differ only by ``MEDALLION_*`` env: each
subscribes to its upstream stage's trigger topic, emits a standard OpenLineage transform event
(``inputs=[from_dataset]`` → ``outputs=[to_dataset]`` — the ``DERIVED_FROM`` edge), and publishes the next
stage's trigger. So a single producer event cascades raw→bronze→silver→gold, and because every hop is a
Dapr publish over the instrumented gRPC client, the W3C trace context propagates → one distributed trace.

Idempotent + best-effort: the transform is a dummy emit (no heavy compute), the graph MERGEs on run_id,
and a publish outage returns ``RETRY`` so the Dapr sidecar redelivers. Run: ``uvicorn medallion.mover:app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from common import fga
from dapr.aio.clients import DaprClient
from fastapi import FastAPI

from medallion.api.events import register_stage_route
from medallion.api.health import router as health_router
from medallion.core.config import get_settings

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.dapr = DaprClient()  # local sidecar; persists publishes to NATS JetStream
    app.state.fga = None
    settings = get_settings()
    if settings.fga_enabled:
        # Provision by store NAME so the mover converges on the catalog's Zanzibar store (idempotent),
        # then check authorization as its own service identity before every transition.
        store_id, model_id = await fga.provision(settings.fga_api_url)
        app.state.fga = fga.make_client(settings.fga_api_url, store_id, model_id)
    try:
        yield
    finally:
        with suppress(Exception):
            await app.state.dapr.close()
        if app.state.fga is not None:
            with suppress(Exception):
                await app.state.fga.close()


app = FastAPI(
    title=f"medallion mover ({_settings.from_namespace}->{_settings.to_namespace})", lifespan=lifespan
)
app.include_router(health_router)
# The DaprApp wrapper serves GET /dapr/subscribe (read by the sidecar at startup) and routes deliveries
# of `sub_topic` to /medallion-event. Each mover has its own app-id + sub_topic, so no consumer clash.
register_stage_route(app)
