"""OpenTelemetry domain metrics for the compaction service (exported OTLP-direct to GreptimeDB)."""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("lance.compaction")

_runs = _meter.create_counter(
    "compaction.runs",
    unit="{run}",
    description="Compaction sweeps triggered by the Dapr cron binding.",
)
_fragments_removed = _meter.create_counter(
    "compaction.fragments.removed",
    unit="{fragment}",
    description="Small Lance fragments merged away by compaction.",
)
_versions_removed = _meter.create_counter(
    "compaction.versions.removed",
    unit="{version}",
    description="Superseded Lance manifest versions GC'd.",
)


def record_run() -> None:
    _runs.add(1)


def record_reclaimed(fragments_removed: int, versions_removed: int) -> None:
    """Record what one sweep reclaimed across all datasets."""
    if fragments_removed:
        _fragments_removed.add(fragments_removed)
    if versions_removed:
        _versions_removed.add(versions_removed)
