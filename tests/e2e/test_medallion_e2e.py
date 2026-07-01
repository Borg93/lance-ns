"""End-to-end test for the event-driven medallion cascade (lance-ray → 3 movers → lineage DAG).

ONE call to lance-ray's ``/produce`` must cascade the whole pipeline — raw → bronze → silver → gold —
purely through Dapr pub/sub, and the lineage graph must end up showing gold transitively derived from
raw. This is the regression guard for "the medallion services are wired and the triggers chain".

Run (port-forward lance-ray + lineage to distinct local ports first), or `make e2e-medallion`:

    kubectl port-forward svc/lance-ns-lance-ray 8002:8000 &
    kubectl port-forward svc/lance-ns-lineage   8000:8000 &
    LANCE_E2E_LANCERAY_URL=http://localhost:8002 LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
    uv run pytest tests/e2e/test_medallion_e2e.py -v
"""

from __future__ import annotations

import os
import time

import pytest
import requests

LANCERAY = os.environ.get("LANCE_E2E_LANCERAY_URL", "")
LINEAGE = os.environ.get("LANCE_E2E_LINEAGE_URL", "")

pytestmark = [pytest.mark.e2e, pytest.mark.medallion]


@pytest.fixture(scope="module")
def urls() -> tuple[str, str]:
    if not (LANCERAY and LINEAGE):
        pytest.skip("set LANCE_E2E_LANCERAY_URL and LANCE_E2E_LINEAGE_URL (see module docstring)")
    for name, url in (("lance-ray", LANCERAY), ("lineage", LINEAGE)):
        try:
            requests.get(f"{url.rstrip('/')}/livez", timeout=5).raise_for_status()
        except Exception:  # noqa: BLE001
            pytest.skip(f"{name} not reachable at {url}")
    return LANCERAY.rstrip("/"), LINEAGE.rstrip("/")


def test_produce_cascades_raw_to_gold(urls: tuple[str, str]) -> None:
    lance_ray, lineage = urls

    # ACT — one trigger at the head of the pipeline.
    produced = requests.post(f"{lance_ray}/produce", timeout=8)
    assert produced.status_code == 202 and produced.json()["status"] == "produced", produced.text

    # ASSERT — the cascade reached gold: its transitive upstream includes every prior stage.
    deadline = time.monotonic() + 60.0
    upstream: list[str] = []
    while time.monotonic() < deadline:
        resp = requests.get(f"{lineage}/datasets/gold$catalog/upstream", timeout=8)
        if resp.status_code == 200:
            upstream = [ref["name"] for ref in resp.json().get("related", [])]
            if {"raw_events", "bronze$events", "silver$features"} <= set(upstream):
                return
        time.sleep(3)
    pytest.fail(f"gold$catalog never derived from the full chain within 60s (saw upstream={upstream})")
