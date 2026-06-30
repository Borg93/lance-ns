"""The lance-ray producer's ``POST /produce`` route — thin wrapper over the produce service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from medallion.api.dependencies import DaprClientDep, SettingsDep
from medallion.services.produce import produce as run_produce

router = APIRouter(tags=["produce"])


@router.post("/produce", status_code=202)
async def produce(dapr: DaprClientDep, settings: SettingsDep) -> dict[str, str]:
    """Ingest (dummy) the raw dataset and fire the first medallion trigger.

    Emits an OpenLineage event for ``raw_events`` then publishes ``{token, dataset}`` to the raw topic.
    Unlike the inline best-effort lineage emit, the trigger publish is the **cascade head** — if it is
    dropped, the entire raw→bronze→silver→gold run silently never happens. So a publish failure surfaces
    as **503** (not the 202 that would hide it), letting the caller retry; the request is otherwise 202.
    """
    result = await run_produce(dapr, settings)
    if result.get("status") == "publish_failed":
        raise HTTPException(status_code=503, detail="medallion trigger publish failed; retry")
    return result
