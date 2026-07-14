"""Live client-DIRECT write e2e (#2) — against the DEPLOYED kind stack (Dex + OpenFGA + catalog + RustFS).

Proves the whole governed client-direct path end to end: a real Dex OIDC token, a real OpenFGA grant, a
server-side create, then the client writes Lance fragments DIRECTLY to RustFS and the catalog folds only
the tiny ``FragmentMetadata`` into a governed metadata-only commit — **zero data bytes transit the
catalog**. Also pins the authz gates (no token → 401, unauthorized user → 403).

Skipped unless ``LANCE_E2E_CATALOG_URL`` is set and reachable. Run via ``make e2e-client-direct``.
"""

from __future__ import annotations

import base64
import json
import os

import lance
import pyarrow as pa
import pytest
import requests

CATALOG = os.environ.get("LANCE_E2E_CATALOG_URL", "").rstrip("/")
DEX = os.environ.get("LANCE_E2E_DEX", "http://localhost:5556/dex").rstrip("/")
FGA = os.environ.get("LANCE_E2E_FGA", "http://localhost:8080").rstrip("/")
S3 = os.environ.get("LANCE_E2E_S3", "http://localhost:9900").rstrip("/")

pytestmark = pytest.mark.e2e

_NS, _TBL = "cddemoe2e", "t"
_TABLE = f"{_NS}${_TBL}"


@pytest.fixture(scope="module")
def catalog() -> str:
    if not CATALOG:
        pytest.skip("set LANCE_E2E_CATALOG_URL (deployed stack) to run the client-direct e2e")
    try:
        requests.get(f"{CATALOG}/livez", timeout=5).raise_for_status()
        requests.get(f"{DEX}/.well-known/openid-configuration", timeout=5).raise_for_status()
        requests.get(f"{FGA}/healthz", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip("client-direct stack (catalog/dex/openfga) not reachable")
    return CATALOG


def _token(user: str) -> str:
    r = requests.post(
        f"{DEX}/token",
        data={
            "grant_type": "password",
            "client_id": "lance-catalog",
            "client_secret": "lance-catalog-secret",
            "username": user,
            "password": "password",
            "scope": "openid",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["id_token"]


def _sub(tok: str) -> str:
    p = tok.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))["sub"]


def _store_model() -> tuple[str, str]:
    stores = requests.get(f"{FGA}/stores", timeout=10).json()["stores"]
    st = sorted(stores, key=lambda s: s["created_at"])[-1]["id"]
    m = requests.get(f"{FGA}/stores/{st}/authorization-models", timeout=10).json()
    return st, m["authorization_models"][0]["id"]


def _grant(st: str, m: str, sub: str, rel: str, obj: str) -> None:
    requests.post(
        f"{FGA}/stores/{st}/write",
        json={
            "writes": {"tuple_keys": [{"user": f"user:{sub}", "relation": rel, "object": obj}]},
            "authorization_model_id": m,
        },
        timeout=10,
    )


def _schema() -> pa.Schema:
    return pa.schema([pa.field("id", pa.int64()), pa.field("v", pa.string())])


def test_client_direct_commit_lands_with_zero_byte_ingress(catalog: str) -> None:
    tok = _token("alice@example.com")
    st, m = _store_model()
    _grant(st, m, _sub(tok), "writer", "warehouse:lance_catalog")
    h = {"Authorization": f"Bearer {tok}"}

    # Server-side create seeds the table (create centralizes the 2.2 invariant; bulk append goes direct).
    requests.post(f"{catalog}/v1/namespace/{_NS}/create", headers=h, json={}, timeout=20)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, _schema()) as w:
        w.write_table(pa.table({"id": [1, 2], "v": ["a", "b"]}, schema=_schema()))
    r = requests.post(
        f"{catalog}/v1/table/{_TABLE}/create",
        headers={**h, "content-type": "application/vnd.apache.arrow.stream"},
        data=sink.getvalue().to_pybytes(),
        params={"mode": "overwrite"},
        timeout=30,
    )
    assert r.status_code in (200, 409), r.text

    # Vend → the client's write target + optimistic base version.
    r = requests.post(
        f"{catalog}/v1/table/{_TABLE}/credentials", headers=h, params={"tier": "write"}, timeout=30
    )
    assert r.status_code == 200, r.text
    cred = r.json()
    location, read_version = cred["location"], cred["read_version"]
    so = (cred.get("credentials") or {}).get("storage_options") or {
        "endpoint": S3,
        "access_key_id": "rustfsadmin",
        "secret_access_key": "rustfsadmin",
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
        "region": "us-east-1",
    }

    # CLIENT-DIRECT: the row data goes straight to RustFS from here — never through the catalog.
    new_rows = pa.table({"id": [3, 4, 5], "v": ["c", "d", "e"]}, schema=_schema())
    frags = lance.fragment.write_fragments(new_rows, location, schema=_schema(), storage_options=so)
    body = json.dumps({"fragments": [f.to_json() for f in frags], "read_version": read_version})

    r = requests.post(
        f"{catalog}/v1/table/{_TABLE}/commit",
        headers={**h, "content-type": "application/json"},
        data=body,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["row_count"] == 5  # 2 seed + 3 appended
    assert resp["version"] >= 2
    # The proof: the commit body is tiny METADATA, not the row data (which went client→RustFS direct).
    assert len(body) < 4096


def test_commit_is_governed(catalog: str) -> None:
    # No token → 401 (OIDC); a valid token without a grant → 403 (FGA) — /commit is NOT an anonymous write.
    body = json.dumps({"fragments": [{"id": 0}], "read_version": 1})
    h = {"content-type": "application/json"}
    assert (
        requests.post(f"{catalog}/v1/table/{_TABLE}/commit", headers=h, data=body, timeout=10).status_code
        == 401
    )
    bob = {**h, "Authorization": f"Bearer {_token('bob@example.com')}"}
    assert (
        requests.post(f"{catalog}/v1/table/{_TABLE}/commit", headers=bob, data=body, timeout=10).status_code
        == 403
    )
