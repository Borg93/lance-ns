"""Demo-only data peek — reads the real Lance datasets on S3 so the UI can show *what is
changing in storage*: the schema at each Lance version, row counts, and gold's embedded JSONB
lineage.

This is **demo instrumentation, not core lineage**. It is mounted only when
``LINEAGE_DEMO_DATA_ENABLED`` is set, reads object storage directly with pylance (the same library
the catalog uses), and never touches the AGE graph. Endpoints are plain ``def`` so FastAPI runs the
blocking Lance I/O in its threadpool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import lance
from fastapi import APIRouter

from lineage.config import get_settings, storage_options
from lineage.schemas import DemoDataset, DemoDatasets, DemoField, DemoVersion

log = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

# The medallion datasets the demo writes — catalog id -> object path under the bucket.
_LAYOUT: list[tuple[str, str]] = [
    ("bronze$events", "bronze/events"),
    ("silver$features", "silver/features"),
    ("gold$catalog", "gold/catalog"),
]


def _storage_options() -> dict[str, str]:
    return storage_options(get_settings())


def _read_lineage_jsonb(ds: Any) -> dict[str, Any] | None:
    """Read gold's embedded ``lineage`` JSONB column (one row) back into a dict."""
    try:
        column = ds.to_table(columns=["lineage"]).column("lineage").to_pylist()
    except Exception:  # noqa: BLE001 - column absent or unreadable
        return None
    if not column:
        return None
    value = column[0]
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _read_dataset(name: str, uri: str, opts: dict[str, str]) -> DemoDataset:
    try:
        ds = lance.dataset(uri, storage_options=opts)
    except Exception:  # noqa: BLE001 - not created yet (a pending dataset is normal mid-demo)
        return DemoDataset(name=name, uri=uri, exists=False)
    versions: list[DemoVersion] = []
    for entry in ds.versions():
        number = int(entry["version"])
        timestamp = entry.get("timestamp")
        try:
            at_version = lance.dataset(uri, storage_options=opts, version=number)
            fields = [DemoField(name=f.name, type=str(f.type)) for f in at_version.schema]
        except Exception:  # noqa: BLE001
            fields = []
        versions.append(
            DemoVersion(
                version=number,
                timestamp=timestamp.isoformat() if hasattr(timestamp, "isoformat") else None,
                fields=fields,
            )
        )
    return DemoDataset(
        name=name,
        uri=uri,
        exists=True,
        current_version=int(ds.version),
        row_count=ds.count_rows(),
        versions=versions,
        lineage_jsonb=_read_lineage_jsonb(ds) if name == "gold$catalog" else None,
    )


@router.get("/datasets", response_model=DemoDatasets)
def demo_datasets() -> DemoDatasets:
    """The medallion datasets as they currently exist on S3 — schema per Lance version + rows."""
    opts = _storage_options()
    bucket = get_settings().s3_bucket
    return DemoDatasets(
        datasets=[_read_dataset(name, f"s3://{bucket}/{path}", opts) for name, path in _LAYOUT]
    )
