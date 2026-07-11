"""Run-status board (``/runs``) and the durable OpenLineage event feed (``/events``).

Both are **durable** (folded onto AGE / read from Postgres — survive restart, replica-shared) and
**governed**: each row is shown only if the caller ``can_get_metadata`` on every dataset it references,
so neither board can enumerate dataset names / creators / errors outside the caller's reach. Auth off →
pass-through.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from lineage.api.dependencies import RepositoryDep, SettingsDep
from lineage.api.fga_deps import FilterDep, governed
from lineage.schemas import Events, Runs

router = APIRouter(tags=["query"])

# /events fetches a wider window than it returns so the visibility filter (which can drop rows) still
# yields up to `limit` newest *visible* events, not "the visible subset of the newest `limit`". (#22
# audit.) The wide window is only needed when FGA can actually drop rows — auth off is pass-through,
# so the fetch window collapses to `limit` there (§2 perf, 2026-07-11: the 2s poll was reading 2000
# full-JSONB rows to return 500).
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
async def get_events(
    repository: RepositoryDep,
    datasets: FilterDep,
    settings: SettingsDep,
    after: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=_EVENTS_RETURN)] = _EVENTS_RETURN,
    summary: bool = False,
) -> Events:
    """The most-recent ingested OpenLineage events (newest first) — the Marquez-style event feed.

    **Durable** (read from Postgres, survives restart / replica-shared) and **governed**: when auth is
    on the feed is filtered like the per-dataset reads — an event is shown only if the caller
    ``can_get_metadata`` on *every* dataset it references (and a dataset-less event is hidden), so the
    audit feed never discloses a table outside the caller's reach. Auth off → pass-through. (#22)

    Pagination (additive, defaults = the old behavior): ``after`` = keyset cursor (the previous
    page's ``next_cursor``); ``limit`` ≤ 500 (server-capped); ``summary=true`` drops the full-JSONB
    ``event`` payload at the SQL layer. The governance filter ALWAYS runs before the slice —
    pagination can never disclose a hidden row's CONTENT. ``next_cursor`` is a WINDOW FLOOR, not
    necessarily a visible row's seq (on a hidden-dense page it is the fetch window's last seq —
    exclusive, so the hidden row itself is never returned; bare seq numbers were already inferable
    from gaps in the pre-pagination feed, so this adds no new disclosure class — reviewed
    2026-07-11).
    """
    # Auth off → governed() is pass-through, so no over-fetch headroom is needed: read exactly
    # `limit` rows. Auth on → keep the wide window so dropped rows don't starve the page.
    fetch = _EVENTS_FETCH if settings.fga_enabled else limit
    records = await repository.list_events(limit=fetch, after=after, summary=summary)
    visible = await governed(
        datasets, settings.fga_enabled, records, lambda r: set(r.inputs) | set(r.outputs)
    )
    returned = visible[:limit]
    if len(returned) == limit and returned:
        next_cursor = returned[-1].seq  # continue right below the last VISIBLE row we returned
    elif len(records) == fetch and records:
        # The fetch window filled up but visibility filtering left a short page — more rows exist
        # below the window; hand back the window's floor so the client can keep paging.
        next_cursor = records[-1].seq
    else:
        next_cursor = None  # the feed is exhausted
    return Events(events=returned, next_cursor=next_cursor)
