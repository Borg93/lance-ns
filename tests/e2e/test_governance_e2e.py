"""Governance end-to-end: catalog authz + lineage provenance, one flow.

Runs against the full governance stack (``scripts/governance_e2e.sh``):
catalog (OIDC + OpenFGA) **+** lineage-api (OpenLineage → Apache AGE), with the catalog's
``LANCE_LINEAGE_EMIT_ENABLED`` on. Skipped unless ``LANCE_E2E_AUTH_SERVER`` and
``LANCE_E2E_LINEAGE_URL`` are set and reachable.

Asserts the dataops/governance story end to end:
  1. anon create → 401 (OIDC enforced);
  2. alice creates namespace + bronze table → 200 (app seeds owner);
  3. bob (no grant) describe → 403; alice (owner) describe → 200 (authz cascade);
  4. the catalog recorded alice as the **verified** creator of bronze in the lineage graph;
  5. a promote run (bronze → silver, as a lance-ray job emits) makes silver's upstream = bronze.

(The lineage service runs with its own auth OFF in this overlay; the gate is unit-tested +
has its own e2e. This test focuses on catalog authz + provenance authorship + medallion lineage.)
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable

import pyarrow as pa
import pytest
import requests

SERVER = os.environ.get("LANCE_E2E_AUTH_SERVER", "")
LINEAGE = os.environ.get("LANCE_E2E_LINEAGE_URL", "")
DEX = os.environ.get("LANCE_E2E_DEX", "http://localhost:5556/dex")
ARROW = {"content-type": "application/vnd.apache.arrow.stream"}

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def stack() -> tuple[str, str]:
    if not (SERVER and LINEAGE):
        pytest.skip("set LANCE_E2E_AUTH_SERVER and LANCE_E2E_LINEAGE_URL to run the governance e2e")
    try:
        requests.get(f"{SERVER}/livez", timeout=5).raise_for_status()
        requests.get(f"{LINEAGE}/livez", timeout=5).raise_for_status()
        requests.get(f"{DEX}/.well-known/openid-configuration", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip("governance stack (catalog / lineage / dex) not reachable")
    return SERVER.rstrip("/"), LINEAGE.rstrip("/")


def _token(username: str) -> str:
    resp = requests.post(
        f"{DEX}/token",
        data={
            "grant_type": "password",
            "client_id": "lance-catalog",
            "username": username,
            "password": "password",
            "scope": "openid",
        },
        timeout=10,
    )
    return resp.json()["id_token"]


def _sub(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def _ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _get_json(url: str) -> dict:
    """GET + parse JSON, degrading to ``{}`` on any transport/non-JSON error (so polls fail cleanly)."""
    try:
        return requests.get(url, timeout=10).json()
    except Exception:  # noqa: BLE001
        return {}


def _poll(fn: Callable[[], object], want: object, *, tries: int = 20, delay: float = 0.5) -> object:
    """Poll ``fn`` until it equals ``want`` — emission is async/fire-and-forget — or give up."""
    last: object = None
    for _ in range(tries):
        last = fn()
        if last == want:
            return last
        time.sleep(delay)
    return last


def test_governance_flow(stack: tuple[str, str]) -> None:
    server, lineage = stack
    alice = _token("alice@example.com")
    alice_sub = _sub(alice)
    bob = _token("bob@example.com")
    ah = {"Authorization": f"Bearer {alice}"}
    bh = {"Authorization": f"Bearer {bob}"}
    ns = f"gov{os.getpid()}"
    bronze, silver = f"{ns}$bronze$events", f"{ns}$silver$events"

    # 1. anon -> 401 (OIDC enforced)
    assert requests.post(f"{server}/v1/namespace/{ns}/create", json={}, timeout=10).status_code == 401

    # 2. alice creates namespace + bronze table -> 200 (app seeds owner; catalog emits create-lineage)
    assert (
        requests.post(f"{server}/v1/namespace/{ns}/create", headers=ah, json={}, timeout=10).status_code
        == 200
    )
    rows = pa.table({"id": pa.array([1, 2, 3], pa.int64())})
    create = requests.post(
        f"{server}/v1/table/{bronze}/create", headers={**ah, **ARROW}, data=_ipc(rows), timeout=30
    )
    assert create.status_code == 200, create.text

    # 3. bob (no grant) cannot describe -> 403 ; alice (owner) can -> 200 (cascade)
    assert requests.post(f"{server}/v1/table/{bronze}/describe", headers=bh, timeout=10).status_code == 403
    assert requests.post(f"{server}/v1/table/{bronze}/describe", headers=ah, timeout=10).status_code == 200

    # 4. lineage recorded alice as the VERIFIED creator (emission is async -> poll)
    creator = _poll(lambda: _get_json(f"{lineage}/datasets/{bronze}/creator").get("creator"), alice_sub)
    assert creator == alice_sub, f"expected lineage creator={alice_sub}, got {creator}"

    # 5. a promote run (bronze -> silver), as a lance-ray job would emit
    promote = {
        "eventType": "COMPLETE",
        "eventTime": "2026-06-24T00:00:00+00:00",
        "run": {
            "runId": f"promote-{os.getpid()}",
            "facets": {"author": {"name": alice_sub, "sub": alice_sub}},
        },
        "job": {"namespace": "lance-ray", "name": "promote_bronze_to_silver"},
        "inputs": [{"namespace": ns, "name": bronze}],
        "outputs": [{"namespace": ns, "name": silver}],
    }
    assert requests.post(f"{lineage}/api/v1/lineage", json=promote, timeout=10).status_code == 201

    # 6. silver's upstream includes bronze (the medallion lineage)
    up = _poll(
        lambda: [r["name"] for r in _get_json(f"{lineage}/datasets/{silver}/upstream").get("related", [])],
        [bronze],
    )
    assert isinstance(up, list) and bronze in up, f"expected {bronze} in silver upstream, got {up}"
