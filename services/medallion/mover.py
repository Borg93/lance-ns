"""A medallion stage mover — one DAG edge, event-driven.

All three movers run THIS module (``medallion.mover:app``) and differ only by ``MEDALLION_*`` env: each
subscribes to its upstream stage's trigger topic, emits a standard OpenLineage transform event
(``inputs=[from_dataset]`` → ``outputs=[to_dataset]`` — the ``DERIVED_FROM`` edge), and publishes the next
stage's trigger. So a single producer event cascades raw→bronze→silver→gold, and because every hop is a
Dapr publish over the instrumented gRPC client, the W3C trace context propagates → one distributed trace.

Idempotent + best-effort: the transform is a dummy emit (no heavy compute), the graph MERGEs on run_id,
and a publish outage returns ``RETRY`` so the Dapr sidecar redelivers. Run: ``uvicorn medallion.mover:app``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from common import fga
from common.dapr_auth import require_dapr_token
from dapr.aio.clients import DaprClient
from dapr.ext.fastapi import DaprApp
from fastapi import Depends, FastAPI, Request

from medallion.config import MedallionSettings, get_settings
from medallion.events import build_run_event
from medallion.metrics import record_denied, record_transition

log = logging.getLogger(__name__)

_SUCCESS = {"status": "SUCCESS"}
_RETRY = {"status": "RETRY"}
_DROP = {"status": "DROP"}

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

# The DaprApp wrapper serves GET /dapr/subscribe (read by the sidecar at startup) and routes deliveries
# of `sub_topic` to the handler below. Each mover has its own app-id + sub_topic, so no consumer clash.
_dapr_app = DaprApp(app)


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


@_dapr_app.subscribe(pubsub=_settings.pubsub, topic=_settings.sub_topic, route="/medallion-event")
async def on_stage(
    event: dict[str, Any], request: Request, _: None = Depends(require_dapr_token)
) -> dict[str, str]:
    """The Dapr subscription route — thin wrapper over the testable :func:`handle_stage`. ``event`` is
    typed ``dict`` so FastAPI parses the CloudEvent JSON body (an ``Any`` param → query param → 422).
    Authenticated by the Dapr app-api-token so a forged stage trigger can't drive the cascade."""
    return await handle_stage(
        request.app.state.dapr, get_settings(), event, fga_client=request.app.state.fga
    )


async def handle_stage(
    dapr: DaprClient, settings: MedallionSettings, event: Any, *, fga_client: Any = None
) -> dict[str, str]:
    """Handle one upstream stage trigger: emit the transform's lineage, then trigger the next stage.
    ``event`` is the untrusted Dapr CloudEvent envelope (hence ``Any`` + the ``isinstance`` guard).

    When ``fga_client`` is set (MEDALLION_FGA_ENABLED), the mover first CHECKS it is authorized to produce
    the target stage — ``can_promote`` for the silver→gold mover, ``can_create_table`` for the others — as
    its own service identity. Unauthorized → ``DROP`` (redelivery won't grant the role): the cascade
    enforces the ReBAC, so a mover lacking the validator role genuinely cannot promote to gold."""
    data = event.get("data") if isinstance(event, dict) else None
    token = data.get("token") if isinstance(data, dict) else None
    transition = f"{settings.from_namespace}->{settings.to_namespace}"

    if fga_client is not None:
        allowed = await fga.check(
            fga_client,
            user=settings.fga_service_identity,
            relation=settings.fga_required_action,
            obj=settings.fga_object(),
        )
        if not allowed:
            record_denied(transition)
            log.warning(
                "medallion_stage_denied",
                extra={
                    "transition": transition,
                    "identity": settings.fga_service_identity,
                    "action": settings.fga_required_action,
                    "object": settings.fga_object(),
                },
            )
            return _DROP

    run_event = build_run_event(
        operation=settings.operation,
        author=settings.author,
        job_namespace=settings.job_namespace,
        inputs=[(settings.from_namespace, settings.from_dataset)],
        output_namespace=settings.to_namespace,
        output_name=settings.to_dataset,
        run_id=f"{settings.operation}-{token}" if token else None,
    )
    try:
        # 1. Emit the transform's lineage (→ the lineage service ingests the DERIVED_FROM edge).
        await dapr.publish_event(
            pubsub_name=settings.pubsub,
            topic_name=settings.lineage_topic,
            data=json.dumps(run_event),
            data_content_type="application/json",
        )
        # 2. Trigger the next stage (unless terminal — gold has no pub_topic).
        if settings.pub_topic:
            await dapr.publish_event(
                pubsub_name=settings.pubsub,
                topic_name=settings.pub_topic,
                data=json.dumps(
                    {"token": token, "dataset": settings.to_dataset, "namespace": settings.to_namespace}
                ),
                data_content_type="application/json",
            )
    except Exception as exc:  # noqa: BLE001 — transient publish failure → let Dapr redeliver
        log.warning(
            "medallion_stage_failed", extra={"transition": transition, "token": token, "error": str(exc)}
        )
        return _RETRY
    record_transition(transition)
    log.info(
        "medallion_stage_moved", extra={"transition": transition, "token": token, "to": settings.to_dataset}
    )
    return _SUCCESS
