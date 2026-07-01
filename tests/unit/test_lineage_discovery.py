"""Unit tests for the lineage discovery endpoints + repository lists (GOAL 4 A1/A2).

Two layers, infra-free (no DB, no network), mirroring ``test_lineage.py`` / ``test_lineage_auth.py``:

* the repository mapping / filter / fold logic (mock ``fetch``), and
* the endpoint governance + pagination (call the handler with a fake repo + ``DatasetFilter``, mock the
  OpenFGA batch check) — proving a page is taken from the *visible* set and non-visible rows are dropped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import lineage.services.repository as repo_mod
import pytest
from common import fga
from common.oidc import IDToken
from fastapi import Request
from lineage.api import fga_deps
from lineage.api.v1.endpoints.discovery import list_datasets, list_jobs, list_namespaces
from lineage.core.config import LineageSettings
from lineage.schemas import DatasetSummary, JobSummary

_ISSUER = "https://idp.example.com"
_FULL_AUTH = {
    "oidc_enabled": True,
    "oidc_issuer": _ISSUER,
    "oidc_audience": "lance",
    "fga_enabled": True,
    "fga_store_id": "store",
    "fga_model_id": "model",
}


def _settings(**values: Any) -> LineageSettings:
    return LineageSettings.model_validate(values)


def _token(sub: str = "alice") -> IDToken:
    return IDToken(iss=_ISSUER, sub=sub, aud="lance", exp=0, iat=0)


def _request(**state: object) -> Request:
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state))))


def _allow(*names: str) -> Callable[..., Awaitable[dict[str, bool]]]:
    """A fake ``fga.batch_check`` that authorizes only ``names`` (every other object is denied)."""
    allowed = set(names)

    async def _batch(_client: object, *, objects: list[str], **_kw: object) -> dict[str, bool]:
        return {o: (o.split(":", 1)[1] in allowed) for o in objects}

    return _batch


def _fetch_returning(rows: list[list[Any]]) -> Callable[..., Awaitable[list[list[Any]]]]:
    async def _fetch(
        _pool: object, _graph: str, _query: str, _params: dict[str, Any] | None = None, *, columns: int = 1
    ) -> list[list[Any]]:
        return rows

    return _fetch


# --- repository layer: list_datasets / list_jobs mapping, filtering, folding ----------------- #


def test_list_datasets_maps_sorts_and_splits_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repo_mod,
        "fetch",
        _fetch_returning([["z$t", "gold", "pii,gold"], ["a$t", "raw", ""], [None, "raw", ""]]),
    )
    repo = repo_mod.LineageRepository(cast(Any, object()), "g")
    out = asyncio.run(repo.list_datasets())
    assert [d.name for d in out] == ["a$t", "z$t"]  # name-sorted; the null-name row is dropped
    assert out[1].tags == ["pii", "gold"]  # comma-joined node prop split back to a list
    assert out[0].namespace == "raw"


def test_list_datasets_filters_by_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_mod, "fetch", _fetch_returning([["a$t", "raw", ""], ["b$t", "gold", ""]]))
    repo = repo_mod.LineageRepository(cast(Any, object()), "g")
    out = asyncio.run(repo.list_datasets(namespace="gold"))
    assert [d.name for d in out] == ["b$t"]


def test_list_datasets_filters_by_tag_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exact membership, not substring — 'pii' must not match a 'pii_masked' tag.
    monkeypatch.setattr(
        repo_mod, "fetch", _fetch_returning([["a$t", "raw", "pii"], ["b$t", "raw", "pii_masked"]])
    )
    repo = repo_mod.LineageRepository(cast(Any, object()), "g")
    out = asyncio.run(repo.list_datasets(tag="pii"))
    assert [d.name for d in out] == ["a$t"]


def test_list_jobs_folds_outputs_and_keeps_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repo_mod,
        "fetch",
        _fetch_returning([["ns", "j1", "d2"], ["ns", "j1", "d1"], ["ns", "j2", None]]),
    )
    repo = repo_mod.LineageRepository(cast(Any, object()), "g")
    out = asyncio.run(repo.list_jobs())
    by_name = {j.name: j for j in out}
    assert by_name["j1"].outputs == ["d1", "d2"]  # two WROTE rows folded + sorted
    assert by_name["j2"].outputs == []  # read-only job → empty output set
    assert [j.name for j in out] == ["j1", "j2"]  # name-sorted


# --- endpoint layer: governance + pagination ------------------------------------------------- #


class _DiscoveryRepo:
    """Minimal repo exposing just the two discovery reads (with canned results)."""

    def __init__(self, datasets: list[DatasetSummary], jobs: list[JobSummary] | None = None) -> None:
        self._datasets = datasets
        self._jobs = jobs or []

    async def list_datasets(
        self, namespace: str | None = None, tag: str | None = None
    ) -> list[DatasetSummary]:  # noqa: ARG002 — filters are exercised at the repository layer
        return list(self._datasets)

    async def list_jobs(self) -> list[JobSummary]:
        return list(self._jobs)


def _ds(*names: str) -> list[DatasetSummary]:
    return [DatasetSummary(name=n, namespace=(n.split("$")[0] if "$" in n else None)) for n in names]


def test_datasets_endpoint_paginates_over_visible_set() -> None:
    # FGA off → everything visible; the page is a slice and total is the full visible count.
    repo = _DiscoveryRepo(_ds("a", "b", "c", "d", "e"))
    flt = fga_deps.DatasetFilter(_request(), _settings(), None)
    result = asyncio.run(list_datasets(cast(Any, repo), flt, _settings(), offset=1, limit=2))
    assert [d.name for d in result.datasets] == ["b", "c"]
    assert result.total == 5


def test_datasets_endpoint_drops_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fga, "batch_check", _allow("a"))  # only "a" is visible
    repo = _DiscoveryRepo(_ds("a", "b"))
    settings = _settings(**_FULL_AUTH)
    flt = fga_deps.DatasetFilter(_request(fga=cast(Any, object())), settings, _token())
    result = asyncio.run(list_datasets(cast(Any, repo), flt, settings))
    assert [d.name for d in result.datasets] == ["a"]
    assert result.total == 1


def test_jobs_endpoint_governed_by_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fga, "batch_check", _allow("a"))  # only "a" is visible
    jobs = [
        JobSummary(namespace="ns", name="ok", outputs=["a"]),  # all outputs visible → kept
        JobSummary(namespace="ns", name="mixed", outputs=["a", "b"]),  # "b" hidden → dropped
        JobSummary(namespace="ns", name="readonly", outputs=[]),  # dataset-less → dropped when governed
    ]
    repo = _DiscoveryRepo([], jobs)
    settings = _settings(**_FULL_AUTH)
    flt = fga_deps.DatasetFilter(_request(fga=cast(Any, object())), settings, _token())
    result = asyncio.run(list_jobs(cast(Any, repo), flt, settings))
    assert [j.name for j in result.jobs] == ["ok"]


def test_namespaces_endpoint_from_visible_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fga, "batch_check", _allow("raw$a"))  # only raw$a is visible
    repo = _DiscoveryRepo(_ds("raw$a", "gold$b"))
    settings = _settings(**_FULL_AUTH)
    flt = fga_deps.DatasetFilter(_request(fga=cast(Any, object())), settings, _token())
    result = asyncio.run(list_namespaces(cast(Any, repo), flt, settings))
    assert result.namespaces == ["raw"]  # gold hidden — its only dataset isn't visible
