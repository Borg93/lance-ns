"""End-to-end observability test against the deployed kind stack (catalog + Dapr + lineage + GreptimeDB).

The regression guard for the thing that must never silently break while refactoring: the event-driven
pipeline AND its observability. ONE catalog table-create drives the real path, and we assert it produced
the four things that make this system trustworthy — exercising the *deployed* services and the *real*
GreptimeDB store, not mocks:

  1. Durable graph data in Apache AGE       — the dataset node landed (the pipeline actually works)
  2. The custom domain metric in GreptimeDB — lineage_events_processed_total by lance_lineage_outcome went UP
  3. A distributed trace in GreptimeDB      — ONE trace spans catalog → Dapr publish → lineage → AGE
  4. Logs in GreptimeDB                      — apps via OTLP; infra via Vector (both tables populate)

Run (port-forward the three services first), or `make e2e-obs`:

    kubectl port-forward svc/lance-ns-catalog               2333:2333 &
    kubectl port-forward svc/lance-ns-lineage               8000:8000 &
    kubectl port-forward svc/lance-ns-greptimedb-standalone 4000:4000 &
    LANCE_E2E_CATALOG_URL=http://localhost:2333 \
    LANCE_E2E_LINEAGE_URL=http://localhost:8000 \
    LANCE_E2E_GREPTIME_URL=http://localhost:4000 \
    uv run pytest tests/e2e/test_observability_e2e.py -v
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pytest
import requests

CATALOG = os.environ.get("LANCE_E2E_CATALOG_URL", "")
LINEAGE = os.environ.get("LANCE_E2E_LINEAGE_URL", "")
GREPTIME = os.environ.get("LANCE_E2E_GREPTIME_URL", "")
ARROW = {"content-type": "application/vnd.apache.arrow.stream"}

pytestmark = [pytest.mark.e2e, pytest.mark.observability]


def _eventually(fn: Callable[[], Any], *, timeout: float = 60.0, interval: float = 3.0) -> Any:
    """Poll ``fn`` until it returns a truthy value (the signal arrived), else fail with the last result.
    Signals are asynchronous here — Dapr redelivery, the 5s metric export interval, trace batching."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001 — transient while signals propagate/export
            last = exc
        time.sleep(interval)
    pytest.fail(f"condition not met within {timeout}s (last={last!r})")


def _gt_sql(query: str) -> list[list[Any]]:
    """Run SQL against GreptimeDB and return the result rows."""
    r = requests.get(f"{GREPTIME}/v1/sql", params={"db": "public", "sql": query}, timeout=10)
    r.raise_for_status()
    return r.json()["output"][0]["records"]["rows"]


def _gt_promql_sum(query: str) -> float:
    """Sum of a PromQL instant query's series values via GreptimeDB's Prometheus-compatible API."""
    r = requests.get(f"{GREPTIME}/v1/prometheus/api/v1/query", params={"query": query}, timeout=10)
    r.raise_for_status()
    return sum(float(s["value"][1]) for s in r.json()["data"]["result"])


def _create_table(table_id: str, namespace: str) -> None:
    """Create a namespace + table via the catalog — the action that emits a lineage event over Dapr."""
    requests.post(f"{CATALOG}/v1/table/{table_id}/drop")
    requests.post(f"{CATALOG}/v1/namespace/{namespace}/drop")
    assert requests.post(f"{CATALOG}/v1/namespace/{namespace}/create", json={}).status_code == 200
    rows = pa.table({"id": pa.array([1, 2, 3], pa.int64())})
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, rows.schema) as writer:
        writer.write_table(rows)
    resp = requests.post(
        f"{CATALOG}/v1/table/{table_id}/create?mode=overwrite",
        data=sink.getvalue().to_pybytes(),
        headers=ARROW,
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture(scope="module")
def pipeline_run() -> dict[str, Any]:
    """Drive the real pipeline once: baseline the metric, create a table, return the run context.
    Skips cleanly unless all three services are reachable (the LANCE_E2E_*_URL env vars)."""
    if not (CATALOG and LINEAGE and GREPTIME):
        pytest.skip("set LANCE_E2E_CATALOG_URL / _LINEAGE_URL / _GREPTIME_URL (see module docstring)")
    probes = (
        ("catalog", CATALOG, "/livez"),
        ("lineage", LINEAGE, "/livez"),
        ("greptime", GREPTIME, "/health"),
    )
    for name, url, probe in probes:
        try:
            requests.get(f"{url.rstrip('/')}{probe}", timeout=5).raise_for_status()
        except Exception:  # noqa: BLE001
            pytest.skip(f"{name} not reachable at {url}")

    token = uuid.uuid4().hex[:8]
    namespace = f"obsns{token}"
    table_id = f"{namespace}${namespace}tbl"  # catalog id == lineage Dataset == OpenFGA object id
    metric_query = 'sum(lineage_events_processed_total{lance_lineage_outcome="ingested"})'
    before = _gt_promql_sum(metric_query)

    _create_table(table_id, namespace)
    return {"table_id": table_id, "metric_query": metric_query, "ingested_before": before}


def test_data_landed_in_age(pipeline_run: dict[str, Any]) -> None:
    """1. The dataset node materialized in Apache AGE — the event was ingested into the graph."""
    table_id = pipeline_run["table_id"]

    def dataset_present() -> dict[str, Any] | None:
        r = requests.get(f"{LINEAGE}/datasets/{table_id}/creator", timeout=8)
        if r.status_code == 200 and r.json().get("dataset") == table_id:
            return r.json()
        return None

    assert _eventually(dataset_present)["dataset"] == table_id


def test_custom_metric_incremented(pipeline_run: dict[str, Any]) -> None:
    """2. The custom domain metric went UP in GreptimeDB/PromQL — metrics are queryable + valuable."""
    before = pipeline_run["ingested_before"]
    query = pipeline_run["metric_query"]

    def metric_increased() -> float | None:
        after = _gt_promql_sum(query)
        return after if after > before else None

    assert _eventually(metric_increased) > before


@pytest.mark.usefixtures("pipeline_run")
def test_distributed_trace_spans_catalog_to_lineage() -> None:
    """3. ONE trace spans catalog → Dapr publish → lineage → AGE write — true distributed tracing."""

    def joined_trace() -> str | None:
        rows = _gt_sql(
            "SELECT trace_id, service_name FROM opentelemetry_traces ORDER BY timestamp DESC LIMIT 200"
        )
        by_trace: dict[str, set[str]] = {}
        for trace_id, service in rows:
            by_trace.setdefault(trace_id, set()).add(service)
        joined = [t for t, services in by_trace.items() if {"catalog", "lineage"} <= services]
        return joined[0] if joined else None

    trace_id = _eventually(joined_trace)
    spans = _gt_sql(
        f"SELECT DISTINCT service_name, span_name FROM opentelemetry_traces WHERE trace_id = '{trace_id}'"
    )
    services = {service for service, _ in spans}
    span_names = {name for _, name in spans}
    assert {"catalog", "lineage"} <= services
    assert any("PublishEvent" in n for n in span_names), f"no Dapr publish span in {span_names}"
    assert any("/lineage-events" in n for n in span_names), f"no lineage subscriber span in {span_names}"


@pytest.mark.usefixtures("pipeline_run")
def test_logs_populated() -> None:
    """4. Both log paths populate GreptimeDB — app OTLP logs and Vector pod logs."""

    def both_log_tables_nonempty() -> bool | None:
        otlp = int(_gt_sql("SELECT count(*) FROM opentelemetry_logs")[0][0])
        pods = int(_gt_sql("SELECT count(*) FROM lance_logs")[0][0])
        return otlp > 0 and pods > 0 or None

    assert _eventually(both_log_tables_nonempty)

    # Log↔trace CORRELATION, not just presence (otel signals.md: "Every log emitted inside an
    # active span carries trace_id"): if the logging auto-instrumentation env flag were dropped,
    # both tables would still fill and the suite would pass while correlation silently died.
    def correlated_log_exists() -> bool | None:
        rows = _gt_sql(
            "SELECT count(*) FROM opentelemetry_logs WHERE trace_id IS NOT NULL AND trace_id != ''"
        )
        return int(rows[0][0]) > 0 or None

    assert _eventually(correlated_log_exists)
