"""The periodic storage->graph reconciliation route — a Dapr cron binding fires the back-fill sweep (B4).

A ``bindings.cron`` component POSTs to ``/<binding-name>`` on a schedule; OPTIONS is Dapr's binding-discovery
pre-flight. The sweep reconciles every dataset the graph knows against on-disk Lance and **back-fills** any
write whose lineage event was lost (the outbox gap) — the buildable half of the outbox problem, since a
stateless catalog over object storage has no DB to host a transactional outbox. Guarded by
``require_dapr_token`` so only the sidecar's cron may drive it. The schedule + binding name live in the
chart, not app code (no scheduler thread here). Blocking Lance/S3 reads run in the threadpool.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from common.dapr_auth import require_dapr_token
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from lineage.api.dependencies import RepositoryDep, SettingsDep
from lineage.core.config import storage_options
from lineage.core.reconcile import (
    BACKFILLABLE_STATES,
    STORAGE_LOSS_STATES,
    read_storage_schema,
    read_storage_version,
    reconcile_all,
)

log = logging.getLogger(__name__)


async def _on_cron(
    repository: RepositoryDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(require_dapr_token)],
) -> dict[str, Any]:
    """One reconciliation sweep, triggered by a Dapr cron tick: back-fill any dropped Lance writes.

    Reconciles every dataset with a dataSource URI against on-disk Lance; a write the graph never recorded
    (storage AHEAD / UNTRACKED) is stamped back onto the graph. The Lance reads run in the threadpool so the
    object-store I/O never stalls the event loop. Best-effort per the cron contract (a bad read is skipped).

    Single-flight: the cron fires on EVERY lineage replica independently, so the sweep runs under a
    cluster-wide advisory lock. A tick that finds a sweep already in progress skips (the next tick retries)
    rather than double-driving the same back-fill.
    """
    async with repository.reconcile_lock() as acquired:
        if not acquired:
            log.info("lineage_reconcile_skipped_locked")
            return {"skipped": True, "reason": "another reconcile sweep is in progress"}
        opts = storage_options(settings)
        statuses = await reconcile_all(
            repository,
            lambda uri: run_in_threadpool(read_storage_version, uri, opts),
            backfill=True,
            # Recover the per-version schema for a back-filled write too (#24), not just its version.
            read_schema=lambda uri: run_in_threadpool(read_storage_schema, uri, opts),
        )
    backfilled = [s.dataset for s in statuses if s.status in BACKFILLABLE_STATES]
    # Surface STORAGE loss (graph claims data on-disk Lance no longer has) — NOT auto-fixable, so log it
    # WARN so a bad restore / storage loss is visible instead of the graph silently serving dead provenance.
    lost = [s.dataset for s in statuses if s.status in STORAGE_LOSS_STATES]
    if lost:
        log.warning("lineage_reconcile_storage_loss", extra={"datasets": lost, "count": len(lost)})
    log.info(
        "lineage_reconcile_sweep",
        extra={"checked": len(statuses), "backfilled": len(backfilled), "storage_loss": len(lost)},
    )
    return {"checked": len(statuses), "backfilled": backfilled, "storage_loss": lost}


async def _ack_binding() -> dict[str, str]:
    """Dapr's startup pre-flight (OPTIONS /<binding-name>) — a 2xx confirms this app consumes the binding."""
    return {"status": "ok"}


def build_reconcile_cron_router(binding_name: str) -> APIRouter:
    """Register the cron route at the exact binding name the sidecar delivers to (POST sweep, OPTIONS ack)."""
    router = APIRouter()
    router.add_api_route(f"/{binding_name}", _on_cron, methods=["POST"], tags=["reconcile"])
    router.add_api_route(f"/{binding_name}", _ack_binding, methods=["OPTIONS"], include_in_schema=False)
    return router
