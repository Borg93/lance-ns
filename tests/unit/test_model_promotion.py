"""Unit tests for the #17 model-registry promotion service (``catalog.services.models``).

Builds a registry Lance dataset the same shape the medallion trainer publishes (``artifact``/``meta`` rows,
append-only, one publish per model version) and exercises the metrics gate + blessed-tag move + describe.
"""

from __future__ import annotations

import json
from typing import Any

import lance
import pyarrow as pa
import pytest
from catalog.services import models as registry
from lance_namespace import (
    InvalidTableStateError,
    TableNotFoundError,
    TableVersionNotFoundError,
)


def _publish(uri: str, metrics: dict[str, Any], token: str, *, first: bool) -> int:
    """Append one model version's rows (mirrors ray_train_job.publish_registry's schema + append)."""
    meta = {"config": {}, "features": ["silver$features"], "metrics": metrics, "token": token}
    table = pa.table(
        {
            "artifact": pa.array(["weights", "config"], pa.string()),
            "meta": pa.array([json.dumps(meta)] * 2, pa.string()),
        }
    )
    if first:
        ds = lance.write_dataset(
            table, uri, mode="overwrite", data_storage_version="2.2", enable_stable_row_ids=True
        )
    else:
        ds = lance.write_dataset(table, uri, mode="append")
    return int(ds.version)


@pytest.fixture
def registry_uri(tmp_path: Any) -> str:
    """A 2-version registry: v1 (rows_seen=4) then v2 (rows_seen=9) — distinct metrics per version."""
    uri = str(tmp_path / "demo")
    v1 = _publish(uri, {"rows_seen": 4, "features": 1}, "tok-v1", first=True)
    v2 = _publish(uri, {"rows_seen": 9, "features": 1}, "tok-v2", first=False)
    assert (v1, v2) == (1, 2)
    return uri


def test_metrics_at_reads_the_right_version(registry_uri: str) -> None:
    # Append-only: each version's OWN metrics (the rows appended at that version), not a blur across versions.
    assert registry.metrics_at(registry_uri, {}, 1) == {"rows_seen": 4, "features": 1}
    assert registry.metrics_at(registry_uri, {}, 2) == {"rows_seen": 9, "features": 1}


def test_promote_moves_the_blessed_tag(registry_uri: str) -> None:
    assert registry.blessed_version(registry_uri, {}) is None  # nothing blessed yet
    assert registry.promote(registry_uri, {}, version=2) == 2
    assert registry.blessed_version(registry_uri, {}) == 2
    # Re-bless an OLDER version — the pointer moves (a tag move mints no new Lance version).
    assert lance.dataset(registry_uri).version == 2
    assert registry.promote(registry_uri, {}, version=1) == 1
    assert registry.blessed_version(registry_uri, {}) == 1
    assert lance.dataset(registry_uri).version == 2  # unchanged — metadata-only move


def test_metrics_gate_blocks_a_version_below_threshold(registry_uri: str) -> None:
    # v1 has rows_seen=4; require >= 8 → refused (409), and the tag is NOT moved.
    with pytest.raises(InvalidTableStateError, match="below required"):
        registry.promote(registry_uri, {}, version=1, min_metrics={"rows_seen": 8})
    assert registry.blessed_version(registry_uri, {}) is None  # nothing blessed — fail-closed


def test_metrics_gate_passes_when_metrics_meet_threshold(registry_uri: str) -> None:
    assert registry.promote(registry_uri, {}, version=2, min_metrics={"rows_seen": 8}) == 2
    assert registry.blessed_version(registry_uri, {}) == 2


def test_metrics_gate_refuses_an_absent_metric(registry_uri: str) -> None:
    # A gate keyed on a metric the run never recorded must REFUSE, never vacuously pass.
    with pytest.raises(InvalidTableStateError, match="absent or non-numeric"):
        registry.promote(registry_uri, {}, version=2, min_metrics={"accuracy": 0.9})
    assert registry.blessed_version(registry_uri, {}) is None


def test_promote_unknown_version_is_404(registry_uri: str) -> None:
    with pytest.raises(TableVersionNotFoundError):
        registry.promote(registry_uri, {}, version=99)


def test_promote_unknown_model_is_404(tmp_path: Any) -> None:
    with pytest.raises(TableNotFoundError):
        registry.promote(str(tmp_path / "never-trained"), {}, version=1)


def test_describe_reports_candidate_and_blessed(registry_uri: str) -> None:
    before = registry.describe(registry_uri, {})
    assert before["latest_version"] == 2
    assert before["blessed_version"] is None
    assert before["candidate_metrics"] == {"rows_seen": 9, "features": 1}
    assert before["blessed_metrics"] is None

    registry.promote(registry_uri, {}, version=1)
    after = registry.describe(registry_uri, {})
    assert after["latest_version"] == 2  # candidate is still the latest
    assert after["blessed_version"] == 1  # but v1 is blessed
    assert after["blessed_metrics"] == {"rows_seen": 4, "features": 1}
