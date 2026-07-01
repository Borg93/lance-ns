"""Discovery endpoints — browse the lineage estate (datasets / jobs / namespaces).

The per-``{name}`` reads in ``datasets.py`` answer *"tell me about X"* — each gated on
``can_get_metadata`` for a name the caller must already know. These answer *"what is there?"*: the
browsable catalog Marquez has and a bare graph store lacks, so a caller (or the UI) never has to know a
name in advance. Each is **governed** exactly like ``/runs`` and ``/events`` — a row referencing a dataset
the caller may not see is dropped, so listing can't disclose tables outside the caller's reach. Auth off →
pass-through.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from lineage.api.dependencies import RepositoryDep, SettingsDep
from lineage.api.fga_deps import FilterDep, governed
from lineage.schemas import Datasets, Jobs, Namespaces

router = APIRouter(tags=["discovery"])

_MAX_LIMIT = 500


@router.get("/datasets")
async def list_datasets(
    repository: RepositoryDep,
    datasets: FilterDep,
    settings: SettingsDep,
    namespace: str | None = None,
    tag: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 100,
) -> Datasets:
    """Browse every dataset the caller may see — the lineage catalog's landing list.

    Governed (a dataset is shown only if the caller ``can_get_metadata`` on it), optionally filtered by
    ``?namespace=`` / ``?tag=``, and paginated over the *visible* set. This is the entry point the graph
    reads (``/datasets/{name}/...``) needed but could not provide — you no longer must know a name first.
    """
    all_datasets = await repository.list_datasets(namespace=namespace, tag=tag)
    visible = await governed(datasets, settings.fga_enabled, all_datasets, lambda d: {d.name})
    return Datasets(datasets=visible[offset : offset + limit], total=len(visible))


@router.get("/jobs")
async def list_jobs(repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep) -> Jobs:
    """The jobs (compute identities) that have run — governed by the datasets each wrote.

    A job is shown only if the caller can see every dataset it wrote (a read-only / output-less job is
    hidden when auth is on, mirroring how ``/events`` drops a dataset-less row). Auth off → pass-through.
    """
    all_jobs = await repository.list_jobs()
    visible = await governed(datasets, settings.fga_enabled, all_jobs, lambda j: set(j.outputs))
    return Jobs(jobs=visible, total=len(visible))


@router.get("/namespaces")
async def list_namespaces(
    repository: RepositoryDep, datasets: FilterDep, settings: SettingsDep
) -> Namespaces:
    """The namespaces containing at least one dataset the caller may see (for a namespace-tree browse).

    Derived from the governed dataset set, so a namespace the caller can see no dataset in never appears.
    """
    all_datasets = await repository.list_datasets()
    visible = await governed(datasets, settings.fga_enabled, all_datasets, lambda d: {d.name})
    return Namespaces(namespaces=sorted({d.namespace for d in visible if d.namespace}))
