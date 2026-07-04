"""The lance-ray producer's ``POST /produce`` route — thin wrapper over the produce service."""

from __future__ import annotations

from typing import Annotated

from common.dapr_auth import require_dapr_token
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from medallion.api.dependencies import DaprClientDep, SettingsDep
from medallion.services.produce import produce as run_produce

router = APIRouter(tags=["produce"])


@router.post("/produce", status_code=202, response_model=None)  # union with JSONResponse → no auto model
async def produce(
    dapr: DaprClientDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(require_dapr_token)],
) -> dict[str, str] | JSONResponse:
    """Ingest (dummy) the raw dataset and emit its write event — the event-driven cascade head.

    Seeds ``raw_events`` (with compute) and emits ONE OpenLineage event for it; lance-ray's ``/raw-arrival``
    subscription reacts to that event and publishes the ``medallion.raw`` trigger, so the cascade is driven
    by the arrival event, not this call. The raw-write emit is therefore the **cascade head** — if it is
    dropped, the entire raw→bronze→silver→gold run silently never happens. So a publish failure surfaces as
    **503** (not the 202 that would hide it), letting the caller retry; the request is otherwise 202.

    Guarded by ``require_dapr_token`` (the shared app-api-token) so an in-cluster workload can't forge the
    cascade head: /produce is a direct operator trigger (not sidecar-delivered), and without this any pod that
    could reach ``lance-ray:8000`` could drive the pipeline / fabricate medallion provenance. No-op in dev
    (unset token); enforced once APP_API_TOKEN is set. A NetworkPolicy (chart) is the network-isolation layer.
    """
    result = await run_produce(dapr, settings)
    if result.get("status") == "publish_failed":
        # RFC 9457 problem+json + Retry-After (parity with catalog/lineage errors), not a bare FastAPI 503.
        return JSONResponse(
            status_code=503,
            media_type="application/problem+json",
            headers={"Retry-After": "5"},
            content={
                "type": "https://lance.org/problems/serviceunavailable",
                "title": "ServiceUnavailable",
                "status": 503,
                "detail": "medallion trigger publish failed; retry",
            },
        )
    return result
