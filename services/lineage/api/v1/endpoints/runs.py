"""Run-status board (``/runs``) and the durable OpenLineage event feed (``/events``).

Both are **durable** (folded onto AGE / read from Postgres — survive restart, replica-shared) and
**governed**: each row is shown only if the caller ``can_get_metadata`` on every dataset it references,
so neither board can enumerate dataset names / creators / errors outside the caller's reach. Auth off →
pass-through.
"""

from __future__ import annotations

from fastapi import APIRouter

from lineage.api.dependencies import RepositoryDep, SettingsDep
from lineage.api.fga_deps import FilterDep, governed
from lineage.schemas import Events, Runs

router = APIRouter(tags=["query"])

# /events fetches a wider window than it returns so the visibility filter (which can drop rows) still
# yields up to _RETURN newest *visible* events, not "the visible subset of the newest _RETURN". (#22 audit)
_EVENTS_FETCH = 2000
_EVENTS_RETURN = 500


@router.get("/runs")
async def get_runs(repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep) -> Runs:
    """Live run-status board — each run's current state folded onto its ``(:Run)`` node in Apache AGE.

    **Durable** (survives restart / replica-shared) and **governed** like ``/events`` and the per-dataset
    reads: a run is shown only if the caller ``can_get_metadata`` on every dataset it wrote, so the board
    can't enumerate dataset names / creators / errors outside the caller's reach. Auth off → pass-through.
    """
    result = await repository.list_runs()
    result.runs = await governed(datasets, settings.fga_enabled, result.runs, lambda r: set(r.outputs))
    return result


@router.get("/events")
async def get_events(repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep) -> Events:
    """The most-recent ingested OpenLineage events (newest first) — the Marquez-style event feed.

    **Durable** (read from Postgres, survives restart / replica-shared) and **governed**: when auth is
    on the feed is filtered like the per-dataset reads — an event is shown only if the caller
    ``can_get_metadata`` on *every* dataset it references (and a dataset-less event is hidden), so the
    audit feed never discloses a table outside the caller's reach. Auth off → pass-through. (#22)
    """
    records = await repository.list_events(limit=_EVENTS_FETCH)
    visible = await governed(
        datasets, settings.fga_enabled, records, lambda r: set(r.inputs) | set(r.outputs)
    )
    return Events(events=visible[:_EVENTS_RETURN])
