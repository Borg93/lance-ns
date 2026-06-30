"""Storage-version reconciliation endpoint (#23) — does the graph agree with the on-disk Lance file?

Our moat over format-unaware catalogs (Marquez, Lakekeeper): because we own a Lance lakehouse we read
the real on-disk version and cross-check it against the version the graph recorded on the ``WROTE`` edge.
Gated on ``can_get_metadata`` for ``{name}`` (router-level); the blocking Lance read runs in the
threadpool so the object-store I/O never stalls the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from lineage.api.dependencies import RepositoryDep, SettingsDep
from lineage.api.fga_deps import audit_read, require_metadata_access
from lineage.core.config import storage_options
from lineage.core.reconcile import read_storage_version, reconcile
from lineage.schemas import ReconcileStatus

# Gate first (require_metadata_access), then log the authorized reconcile read (#6); deps run in order.
router = APIRouter(
    prefix="/datasets",
    tags=["query"],
    dependencies=[Depends(require_metadata_access), Depends(audit_read)],
)


@router.get("/{name}/reconcile")
async def get_reconcile(name: str, repository: RepositoryDep, settings: SettingsDep) -> ReconcileStatus:
    """Does the lineage graph agree with the **actual Lance file on storage**? (#23)

    Our moat over format-unaware catalogs (Marquez, Lakekeeper): because we own a Lance lakehouse we
    read the real on-disk version and cross-check it against the version the graph recorded on the
    ``WROTE`` edge — surfacing a write that bypassed lineage (``storage_ahead``) or a lineage claim
    with no data behind it (``missing_on_storage``). Gated on ``can_get_metadata`` for ``name``; the
    Lance read runs in the threadpool so the blocking object-store I/O never stalls the event loop.
    """
    graph_version = await repository.latest_write_version(name)
    uri = await repository.source_uri(name)
    storage_version = (
        await run_in_threadpool(read_storage_version, uri, storage_options(settings))
        if uri is not None
        else None
    )
    return reconcile(dataset=name, graph_version=graph_version, storage_version=storage_version)
