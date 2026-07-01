"""Dapr pub/sub subscription wiring for durable catalog→lineage ingest (#25).

The catalog publishes OpenLineage events to the Dapr ``pubsub.jetstream`` component; the sidecar
delivers each one to this service over HTTP. ``DaprApp(app)`` also serves GET ``/dapr/subscribe`` (the
registration the sidecar reads at startup); it is wired unconditionally — harmless without a sidecar —
while the actual subscription is registered only when Dapr ingest is enabled, so an HTTP-only deployment
carries no always-live ingest route.

The thin ``main`` builds ``app`` first, then calls :func:`register_dapr` so the subscription is wired
after ``app`` exists (the import-order constraint the split must preserve).
"""

from __future__ import annotations

from typing import Annotated, Any

from common.dapr_auth import require_dapr_token
from dapr.ext.fastapi import DaprApp
from fastapi import Depends, FastAPI, Request

from lineage.core.config import get_settings
from lineage.services.consumer import handle_cloud_event


async def on_lineage_event(
    event: dict[str, Any], request: Request, _: Annotated[None, Depends(require_dapr_token)]
) -> dict[str, str]:
    """Ingest one Dapr-delivered OpenLineage CloudEvent into the graph; returns the Dapr ack status.

    Authenticated by the Dapr **app-api-token** (``require_dapr_token``): without this the route was an
    unauthenticated, publicly-reachable ingest path co-mounted on the query app — a forged POST could
    self-assert any ``author`` and inject fabricated nodes/edges into the authoritative AGE graph,
    *even with OIDC/FGA on* (the security-audit prod-blocker). The catalog stamps the verified author;
    the token guard ensures only the sidecar (carrying the secret) can deliver."""
    return await handle_cloud_event(request.app.state.repository, event)


def register_dapr(app: FastAPI) -> None:
    """Wire the Dapr subscription onto ``app``.

    ``DaprApp(app)`` is always constructed (it adds GET ``/dapr/subscribe``). The subscription itself is
    registered ONLY when Dapr ingest is enabled, so an HTTP-only deployment carries no always-live ingest
    route. Combined with the token guard above, the pubsub component's publisher scopes, and the gateway
    blocking this route, a forged external event cannot reach the graph."""
    settings = get_settings()
    dapr_app = DaprApp(app)
    if settings.dapr_enabled:
        dapr_app.subscribe(pubsub=settings.dapr_pubsub, topic=settings.dapr_topic, route="/lineage-events")(
            on_lineage_event
        )
