"""Authenticate Dapr-delivered routes (pub/sub subscriptions + input bindings).

Dapr delivers events to the SAME FastAPI app that serves the public HTTP API (``/lineage-events``,
``/medallion-event``, the compaction cron route), so without a check any client that can reach the port
can POST a forged CloudEvent — bypassing ``enforce_author`` and poisoning the authoritative lineage
graph (security audit, prod-blocker). When the pod is annotated ``dapr.io/app-token-secret``, Dapr
injects ``APP_API_TOKEN`` into the app **and** adds a ``dapr-api-token`` header to every request it
delivers. This dependency rejects any delivery whose header doesn't match.

Defense-in-depth (the token is one layer): the ``pubsub.jetstream`` component is **scoped** to the
trusted app-ids (only they can publish to the topic), the gateway **blocks** these routes from external
traffic, and the route is only registered when Dapr is enabled. No ``APP_API_TOKEN`` set = the open dev
default (documented); set it in any deployment that must be trusted.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException


def require_dapr_token(dapr_api_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject a sidecar-delivered request whose ``dapr-api-token`` header doesn't
    match the app's ``APP_API_TOKEN`` (set by Dapr from ``dapr.io/app-token-secret``). No-op when the
    token is unset — the open dev default."""
    expected = os.environ.get("APP_API_TOKEN")
    if expected and dapr_api_token != expected:
        raise HTTPException(status_code=403, detail="invalid or missing Dapr app-api-token")
