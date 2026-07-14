"""#3-A — live per-warehouse physical isolation against the DEPLOYED catalog.

Proves the completion condition end to end: an admin provisions warehouse A→bucket-a and B→bucket-b
(distinct buckets, created at RUNTIME by the API — not the Helm mc-mb loop); a namespace bound to A + a
table created under it physically land in bucket-a and are ABSENT from bucket-b; and ``POST /v1/warehouses``
as a non-admin is denied 403.

Skipped unless ``LANCE_E2E_CATALOG_URL`` + ``LANCE_E2E_TOKEN`` are set (the stack deployed with
``LANCE_WAREHOUSES_ENABLED=true`` and the token's user granted ``can_create_warehouse`` on the project).
Run via ``make e2e-warehouses``. The 403 leg additionally needs ``LANCE_E2E_NONADMIN_TOKEN``.
"""

from __future__ import annotations

import io
import os

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.ipc as ipc
import pytest
import requests

CATALOG = os.environ.get("LANCE_E2E_CATALOG_URL", "").rstrip("/")
TOKEN = os.environ.get("LANCE_E2E_TOKEN", "")
NONADMIN = os.environ.get("LANCE_E2E_NONADMIN_TOKEN", "")
PROJECT = os.environ.get("LANCE_E2E_PROJECT", "acme")
DELIM = os.environ.get("LANCE_E2E_DELIM", "$")
S3 = os.environ.get("LANCE_E2E_S3", "http://localhost:9900")
ARROW_STREAM = "application/vnd.apache.arrow.stream"

pytestmark = pytest.mark.e2e


def _auth() -> dict[str, str]:
    return {"authorization": f"Bearer {TOKEN}"}


def _fs() -> pafs.S3FileSystem:
    return pafs.S3FileSystem(
        access_key="rustfsadmin", secret_key="rustfsadmin", endpoint_override=S3, scheme="http", region=""
    )


def _list_bucket(bucket: str) -> list[str]:
    fs = _fs()
    infos = fs.get_file_info(pafs.FileSelector(bucket, allow_not_found=True, recursive=True))
    return [i.path for i in infos]


def _arrow_ipc() -> bytes:
    table = pa.table({"id": pa.array([1, 2, 3], pa.int64()), "v": pa.array(["a", "b", "c"])})
    sink = io.BytesIO()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


@pytest.fixture(scope="module")
def catalog() -> str:
    if not CATALOG or not TOKEN:
        pytest.skip("set LANCE_E2E_CATALOG_URL + LANCE_E2E_TOKEN (deployed stack with warehouses enabled)")
    try:
        requests.get(f"{CATALOG}/livez", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip("catalog not reachable")
    return CATALOG


def test_per_warehouse_physical_isolation(catalog: str) -> None:
    wh_a, wh_b = "e2e-wh-a", "e2e-wh-b"
    for wid in (wh_a, wh_b):
        r = requests.post(
            f"{catalog}/v1/warehouses", json={"id": wid, "project": PROJECT}, headers=_auth(), timeout=30
        )
        assert r.status_code == 200, r.text
        assert r.json()["root_uri"] == f"s3://{wid}"  # distinct physical bucket per warehouse

    # A namespace bound to warehouse A, then a table under it — both must land in bucket-a.
    r = requests.post(
        f"{catalog}/v1/warehouses/{wh_a}/namespaces",
        json={"namespace": "e2ens"},
        headers=_auth(),
        timeout=30,
    )
    assert r.status_code == 200, r.text

    r = requests.post(
        f"{catalog}/v1/table/e2ens{DELIM}e2etbl/create",
        data=_arrow_ipc(),
        headers={**_auth(), "content-type": ARROW_STREAM},
        timeout=60,
    )
    assert r.status_code == 200, r.text

    a_objs = _list_bucket(wh_a)
    b_objs = _list_bucket(wh_b)
    # The table's Lance data is physically in bucket-a...
    assert any("e2ens" in o or "e2etbl" in o for o in a_objs), a_objs
    # ...and NOT in bucket-b (physical tenant isolation).
    assert not any("e2etbl" in o for o in b_objs), b_objs


def test_create_warehouse_denied_for_non_admin(catalog: str) -> None:
    if not NONADMIN:
        pytest.skip("set LANCE_E2E_NONADMIN_TOKEN to exercise the 403 admin-gate leg")
    r = requests.post(
        f"{catalog}/v1/warehouses",
        json={"id": "e2e-wh-x", "project": PROJECT},
        headers={"authorization": f"Bearer {NONADMIN}"},
        timeout=30,
    )
    assert r.status_code == 403, r.text
