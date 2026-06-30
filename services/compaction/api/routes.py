"""The Dapr cron HTTP surface: the binding-name POST route (runs one sweep) + its OPTIONS ack.

A ``bindings.cron`` component POSTs to ``/<binding-name>`` every interval; OPTIONS is Dapr's
binding-discovery pre-flight. The POST is guarded by ``require_dapr_token`` so only the sidecar's cron
tick may trigger a sweep. Blocking Lance/S3 IO runs in the threadpool so the event loop stays free.
"""

from __future__ import annotations

import logging
from typing import Any

from common.dapr_auth import require_dapr_token
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from compaction.api.dependencies import SettingsDep
from compaction.core.config import get_settings
from compaction.services.sweep import run_sweep, summarize

log = logging.getLogger(__name__)

router = APIRouter()


async def on_cron(settings: SettingsDep) -> dict[str, Any]:
    """One maintenance sweep, triggered by a Dapr cron tick (POST /<binding-name>)."""
    summary = summarize(await run_in_threadpool(run_sweep, settings))
    log.info("compaction_sweep", extra=summary)
    return summary


async def ack_binding() -> dict[str, str]:
    """Dapr's startup pre-flight (OPTIONS /<binding-name>) — a 2xx confirms this app consumes the binding."""
    return {"status": "ok"}


# Register the cron route at the exact binding name the sidecar delivers to: POST runs the sweep, OPTIONS
# acks Dapr's binding-discovery pre-flight (else it 405s and Dapr logs the app as not consuming it).
_binding_name = get_settings().binding_name
router.add_api_route(
    f"/{_binding_name}",
    on_cron,
    methods=["POST"],
    tags=["compaction"],
    dependencies=[Depends(require_dapr_token)],  # only the sidecar's cron tick may trigger a sweep
)
router.add_api_route(f"/{_binding_name}", ack_binding, methods=["OPTIONS"], include_in_schema=False)
