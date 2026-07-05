"""Publish to the Dapr sidecar under a timeout — a hung sidecar must not pin the worker.

``DaprClient.publish_event`` awaits the local sidecar with no reliable client-side timeout, so a wedged
sidecar (or a NATS stall) blocks the calling coroutine indefinitely: a mover never reaches its RETRY, a
best-effort lineage emit never returns. Wrapping every publish in ``asyncio.timeout`` turns that into a
``TimeoutError`` the existing failure path already handles (mover → RETRY / redeliver; catalog+compaction emit
→ best-effort swallow). One helper so the timeout is applied consistently at every publish site.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def publish_event(publisher: Any, *, timeout_seconds: float, **kwargs: Any) -> None:
    """``await publisher.publish_event(**kwargs)`` bounded by ``timeout_seconds`` (raises ``TimeoutError``).

    ``publisher`` is any Dapr client (``dapr.aio.clients.DaprClient`` / the lineage emitter's client) — typed
    ``Any`` because their concrete ``publish_event`` signatures differ; the helper only forwards + times out.
    """
    async with asyncio.timeout(timeout_seconds):
        await publisher.publish_event(**kwargs)
