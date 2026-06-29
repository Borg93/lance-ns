"""Guard against frontend↔backend schema drift (#24).

The web app's TypeScript types are generated from ``web/openapi.json`` (which is dumped from this
FastAPI app). If a route or response model is added/changed but the contract snapshot isn't
regenerated, the frontend types silently lie. This test fails when that happens.

To fix a failure: ``cd web && bun run gen:openapi && bun run gen:types`` and commit the result.
"""

from __future__ import annotations

import json
from pathlib import Path

_OPENAPI = Path(__file__).resolve().parents[2] / "web" / "openapi.json"


def test_committed_openapi_contract_covers_the_live_app() -> None:
    from lineage.main import app

    committed = json.loads(_OPENAPI.read_text())
    live = app.openapi()

    # The committed snapshot is generated with the demo router enabled (a superset of routes/schemas),
    # so the live app — demo on or off — must be a SUBSET. A new path/schema absent here means stale.
    missing_paths = set(live["paths"]) - set(committed["paths"])
    assert not missing_paths, f"web/openapi.json stale — missing paths {sorted(missing_paths)}; regenerate"

    live_schemas = set(live.get("components", {}).get("schemas", {}))
    missing_schemas = live_schemas - set(committed.get("components", {}).get("schemas", {}))
    assert not missing_schemas, (
        f"web/openapi.json is stale — missing schemas {sorted(missing_schemas)}; regenerate."
    )
