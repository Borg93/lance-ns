"""The lance-ray producer's ``POST /produce`` route — thin wrapper over the produce service."""

from __future__ import annotations

from fastapi import APIRouter

from medallion.api.dependencies import DaprClientDep, SettingsDep
from medallion.services.produce import produce as run_produce

router = APIRouter(tags=["produce"])


@router.post("/produce", status_code=202)
async def produce(dapr: DaprClientDep, settings: SettingsDep) -> dict[str, str]:
    """Ingest (dummy) the raw dataset and fire the first medallion trigger.

    Emits an OpenLineage event for ``raw_events`` then publishes ``{token, dataset}`` to the raw topic.
    Best-effort: a sidecar/broker outage logs + still returns (the catalog-style contract)."""
    return await run_produce(dapr, settings)
