"""#75 on-demand garbage-collection endpoints — preview (dry-run reclaimable versions) + run, per table.

Both are owner-gated by the router (``maintenance/preview`` / ``maintenance/run`` → ``can_drop`` in
fga_deps — reclaiming version history is the drop rung, exactly like the retention policy that schedules it).
The preview never mutates; the run reclaims old versions with the sweep's tag exemption. The heavy Lance
work (open dataset, list versions, cleanup) runs in a threadpool so the event loop stays free.
"""

from __future__ import annotations

from typing import Self

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from catalog.api.dependencies import NamespaceDep, SettingsDep, StorageOptionsDep
from catalog.core.identifiers import parse_identifier
from catalog.core.namespace import open_dataset
from catalog.services import maintenance

router = APIRouter(prefix="/v1/table", tags=["maintenance"])


class GcRequest(BaseModel):
    """The GC bounds — a version is reclaimable only if it clears BOTH given bounds (older than
    ``retention_days`` AND outside the most-recent ``retain_versions``). At least one is required."""

    retention_days: int | None = Field(default=None, ge=1, le=3650)
    retain_versions: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def _one_bound(self) -> Self:
        if self.retention_days is None and self.retain_versions is None:
            raise ValueError("provide retention_days and/or retain_versions")
        return self


class GcPreview(BaseModel):
    current_version: int
    total_versions: int
    eligible_versions: list[int]
    protected_tags: dict[str, int]
    retention_days: int | None
    retain_versions: int | None


class GcRunResult(BaseModel):
    ok: bool
    old_versions_removed: int
    bytes_removed: int


class CompactRequest(BaseModel):
    """Optional #76 target-size override for a one-off compaction (None → Lance's default fragment sizing)."""

    target_rows_per_fragment: int | None = Field(default=None, ge=1024, le=10_000_000)


class CompactResult(BaseModel):
    ok: bool
    fragments_removed: int
    fragments_added: int


@router.post("/{id}/maintenance/preview")
async def preview_maintenance(
    id: str, body: GcRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> GcPreview:
    """Dry-run the old-version cleanup — the versions GC would reclaim + the tags protecting others. Owner-
    gated (``can_drop``); never mutates."""
    segments = parse_identifier(id, settings.delimiter)
    ds = await run_in_threadpool(open_dataset, ns, so, segments)
    result = await run_in_threadpool(
        maintenance.preview_gc,
        ds,
        retention_days=body.retention_days,
        retain_versions=body.retain_versions,
    )
    return GcPreview(**result)


@router.post("/{id}/maintenance/run")
async def run_maintenance(
    id: str, body: GcRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> GcRunResult:
    """Reclaim old versions on demand (DESTRUCTIVE; tag-pinned versions are exempt). Owner-gated
    (``can_drop``) — the same bar as scheduling it via the retention policy."""
    segments = parse_identifier(id, settings.delimiter)
    ds = await run_in_threadpool(open_dataset, ns, so, segments)
    result = await run_in_threadpool(
        maintenance.run_gc, ds, retention_days=body.retention_days, retain_versions=body.retain_versions
    )
    return GcRunResult(**result)


@router.post("/{id}/maintenance/compact")
async def compact_maintenance(
    id: str, body: CompactRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> CompactResult:
    """Compact small fragments on demand (#76 'compact now'). Owner-gated (``can_drop``) — the same bar as
    the retention policy that schedules maintenance. Non-destructive: writes a new version, removes none."""
    segments = parse_identifier(id, settings.delimiter)
    ds = await run_in_threadpool(open_dataset, ns, so, segments)
    result = await run_in_threadpool(
        maintenance.compact_now, ds, target_rows_per_fragment=body.target_rows_per_fragment
    )
    return CompactResult(**result)
