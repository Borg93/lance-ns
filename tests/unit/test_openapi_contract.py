"""Guard against frontend↔backend schema drift (#24).

The frontend zones generate their TypeScript catalog/lineage types from the committed
``docs/{catalog,lineage}-openapi.json`` specs (``bun run gen:types:catalog``), which ``make openapi`` dumps
from these FastAPI apps. If a route or response model is added/changed but the committed spec isn't
regenerated, the generated frontend types silently lie. This test fails when a committed spec no longer
covers its live app.

To fix a failure: run ``make openapi`` and commit the updated ``docs/*-openapi.json`` (then re-run the
frontend's ``bun run gen:types:catalog`` if the catalog spec changed).

(Pre-P5 this read ``frontend/apps/web/openapi.json``; that path was retired with apps/web, and the zones now
consume ``docs/*-openapi.json`` directly — so the guard moved here, alongside the ``make openapi-check`` CI
gate that catches the same drift from the other direction.)
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

_DOCS = Path(__file__).resolve().parents[2] / "docs"


@pytest.mark.parametrize(
    ("module", "spec"),
    [("catalog.main", "catalog-openapi.json"), ("lineage.main", "lineage-openapi.json")],
)
def test_committed_openapi_contract_covers_the_live_app(module: str, spec: str) -> None:
    app = importlib.import_module(module).app
    committed = json.loads((_DOCS / spec).read_text())
    live = app.openapi()

    # The committed snapshot is a superset (dumped with any demo router enabled), so the live app — demo on
    # or off — must be a SUBSET. A live path/schema absent from the committed spec means it went stale.
    missing_paths = set(live["paths"]) - set(committed["paths"])
    assert not missing_paths, (
        f"docs/{spec} is stale — missing paths {sorted(missing_paths)}; run 'make openapi'"
    )

    live_schemas = set(live.get("components", {}).get("schemas", {}))
    missing_schemas = live_schemas - set(committed.get("components", {}).get("schemas", {}))
    assert not missing_schemas, (
        f"docs/{spec} is stale — missing schemas {sorted(missing_schemas)}; run 'make openapi'"
    )
