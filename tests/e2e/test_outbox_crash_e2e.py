"""#4 — REAL crash injection: SIGKILL a producer between the Lance commit and the publish ack.

This is the test the outbox actually exists for, and it never existed. The prior e2e *simulated* a crash by
writing the staged object itself, then asserted the relay drained it — which proves the relay works but says
NOTHING about the half that can actually lose data: whether a producer that DIES mid-flight leaves a
recoverable event behind. A mocked exception is not a crash. A `with pytest.raises(TimeoutError)` unwinds
the stack, runs `finally` blocks, and flushes buffers; SIGKILL does none of that. The distinction is the
whole point of the feature.

What this drives, for real:
  1. a child process stages a full RunEvent to the object-store outbox — exactly as
     `publish_lineage_with_outbox` does, in the window AFTER the Lance commit,
  2. the OS kills it with SIGKILL (-9) before it can publish or drop — no cleanup, no finally, no flush,
  3. the staged object must SURVIVE on object storage (the durable copy is all that is left),
  4. the reconcile relay must drain it into BOTH the AGE graph and the durable `/events` feed,
  5. the outbox must end empty (the recovered object is removed, not left to re-ingest forever).

Skipped unless the live stack env is set. Run via `make e2e-ci` / the CI `e2e-stack` job.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest
import requests
from common import outbox
from medallion.schemas.events import build_run_event

LINEAGE = os.environ.get("LANCE_E2E_LINEAGE_URL", "").rstrip("/")
DAPR_TOKEN = os.environ.get("LANCE_E2E_DAPR_TOKEN", "")
BINDING = os.environ.get("LANCE_E2E_RECONCILE_BINDING", "lineage-reconcile-cron")
OUTBOX_URI = os.environ.get("LANCE_E2E_OUTBOX_URI", "s3://lance-catalog/_lineage_outbox")
S3 = os.environ.get("LANCE_E2E_S3", "http://localhost:9900")

pytestmark = pytest.mark.e2e


def _so() -> dict[str, str]:
    return {
        "endpoint": S3,
        "access_key_id": "rustfsadmin",
        "secret_access_key": "rustfsadmin",
        "region": "us-east-1",
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
    }


@pytest.fixture(scope="module")
def lineage() -> str:
    if not LINEAGE or not DAPR_TOKEN:
        pytest.skip("set LANCE_E2E_LINEAGE_URL + LANCE_E2E_DAPR_TOKEN (deployed stack, outbox enabled)")
    try:
        requests.get(f"{LINEAGE}/livez", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip("lineage service not reachable")
    return LINEAGE


def _kill_producer_mid_flight(event_json: str, run_id: str) -> None:
    """Spawn a real producer, let it stage, then SIGKILL it before it can publish or drop.

    The child stages the event and then blocks forever. We kill it with -9 from the parent: the process dies
    with the staged object on disk and no publish — byte-for-byte the state a crashed mover leaves behind.
    """
    child = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.path.join(os.getcwd(), "services")!r})
        from common import outbox
        outbox.stage_event({OUTBOX_URI!r}, {_so()!r}, {run_id!r}, {event_json!r})
        print("STAGED", flush=True)          # the commit→publish window is now OPEN
        time.sleep(300)                       # ...and we die inside it
    """)
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        # wait for the child to confirm it staged (do not race the kill against the write)
        deadline = time.time() + 30
        assert proc.stdout is not None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if line.strip() == "STAGED":
                break
            if proc.poll() is not None:
                raise AssertionError(f"producer died early: {proc.stderr.read() if proc.stderr else ''}")
        else:
            raise AssertionError("producer never staged the event")

        # SIGKILL — not SIGTERM. No handlers, no finally, no buffer flush. The real thing.
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        assert proc.returncode == -signal.SIGKILL, f"expected SIGKILL, got returncode {proc.returncode}"
    finally:
        if proc.poll() is None:  # never leak the child if an assertion blew up above
            proc.kill()
            proc.wait(timeout=5)


def test_sigkilled_producer_loses_nothing(lineage: str) -> None:
    event = build_run_event(
        operation="e2e_crash_probe",
        author="e2e",
        job_namespace="medallion",
        inputs=[("raw", "e2e_crash_src")],
        output_namespace="bronze",
        output_name="e2e_crash_ds",
        version=1,
        token="e2e-crash-probe",
    )
    run_id = event["run"]["runId"]
    event_json = json.dumps(event)

    # 1-2. a REAL producer stages, then the OS kills it dead inside the commit→publish window.
    _kill_producer_mid_flight(event_json, run_id)

    # 3. The durable copy is all that survived the kill. If this fails, #4 does not work at all.
    assert run_id in dict(outbox.list_events(OUTBOX_URI, _so())), (
        "the SIGKILLed producer left NO staged event — the commit→publish loss window is still open"
    )

    # 4. The relay recovers it.
    resp = requests.post(f"{lineage}/{BINDING}", headers={"dapr-api-token": DAPR_TOKEN}, timeout=60)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("outbox_drained", 0) >= 1, resp.text  # increments only on a successful ingest

    # 5. ...and cleans up, so the object cannot be re-ingested forever.
    assert run_id not in dict(outbox.list_events(OUTBOX_URI, _so()))
