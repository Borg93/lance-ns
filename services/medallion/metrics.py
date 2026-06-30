"""OpenTelemetry domain metrics for the medallion pipeline.

The golden signal for the cascade: how many stage transitions each mover completed. Exported via the
OTel SDK (``opentelemetry-instrument``) over OTLP to GreptimeDB, queryable in PromQL / Perses. Bounded
cardinality — only the ``transition`` label (e.g. ``raw->bronze``); per-run ids stay on spans/logs.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("lance.medallion")

_stage_transitions = _meter.create_counter(
    "medallion.stage.transitions",
    unit="{transition}",
    description="Medallion stage transitions completed, by transition (e.g. raw->bronze).",
)
_stage_denied = _meter.create_counter(
    "medallion.stage.denied",
    unit="{transition}",
    description="Stage transitions DENIED by the FGA gate (the mover lacked the required role).",
)


def record_transition(transition: str) -> None:
    """Increment the stage-transition counter for ``transition`` (``"<from>-><to>"``)."""
    _stage_transitions.add(1, {"transition": transition})


def record_denied(transition: str) -> None:
    """Increment the denied counter (the mover was not authorized to produce the target stage)."""
    _stage_denied.add(1, {"transition": transition})
