"""Operational health endpoints (``/livez``, ``/readyz``) shared by both medallion apps.

Cheap liveness/readiness probes — no dependency calls (a Dapr/broker blip must not pull the pod; the
sidecar owns publish retry; no DLQ). Mounted without an API-version prefix on the mover and the producer.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/livez")
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}
