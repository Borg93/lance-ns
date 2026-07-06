"""Governed FULL-UNION e2e — the shipped combination, driven live (§7's last coverage hole).

Every flag at once: **OIDC auth ON + OpenFGA ON (catalog, lineage reads, movers) + compute ON +
quality gate ON**, against the real kind stack (Dapr/NATS/AGE/RustFS/Dex/OpenFGA). The recurring bug
class here is the never-driven union — each feature green in isolation while the composition breaks —
so this suite asserts, live:

  1. the governed ALLOW path: one ``/produce`` cascades raw→bronze→silver→gold with the seeded service
     grants, correlated by the deterministic per-stage run ids; quality verdicts recorded; and the same
     stack really enforces (anon → 401, ungranted user → 403);
  2. FGA-deny → DROP: with the gold validator tuple revoked, the SAME drive stops at silver — gold's
     run never lands — and re-granting makes the next drive cascade again (the tuple is the only delta);
  3. quality-block: a bad batch (null ids) written to bronze is derived into silver, the gate records
     ``quality_passed=false`` + the failed ``not_null`` assertion in lineage, and gold is NOT triggered;
  4. the MEDIA lane under governance: ``/ingest-media`` lands blobs + derives thumbnail/embedding with
     the seeded ``service-media-to-silver`` grant, all read back through the GOVERNED lineage API.

Deploy the union + seed, then ``make e2e-governed-union`` (which port-forwards + seeds + fills env):

    helm upgrade --install lance-ns ./chart --set image.catalog.tag=dev --set image.web.tag=dev \\
      --set auth.enabled=true --set medallion.fgaEnabled=true \\
      --set medallion.compute=true --set medallion.quality=true --set openbao.enabled=false

Human lineage reads work because ``scripts/seed_medallion_fga.sh`` links every cascade dataset to its
stage namespace (table→namespace parent tuples) — the suite only grants its own reader on the warehouse.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from collections.abc import Callable

import pytest
import requests

LANCERAY = os.environ.get("LANCE_E2E_LANCERAY_URL", "")
LINEAGE = os.environ.get("LANCE_E2E_LINEAGE_URL", "")
DEX = os.environ.get("LANCE_E2E_DEX", "http://localhost:5556/dex")
DEX_SECRET = os.environ.get("LANCE_E2E_DEX_SECRET", "lance-catalog-secret")
FGA = os.environ.get("LANCE_E2E_FGA", "")
DAPR_TOKEN = os.environ.get("LANCE_E2E_DAPR_TOKEN", "")
# The bronze→silver mover, for the quality-block direct drive (movers have no k8s Service — the make
# target port-forwards the deployment) + its app token (the same guard its sidecar delivery carries).
MOVER_URL = os.environ.get("LANCE_E2E_MOVER_URL", "")
MOVER_TOKEN = os.environ.get("LANCE_E2E_MOVER_TOKEN", "")
S3_ENDPOINT = os.environ.get("LANCE_E2E_S3_ENDPOINT", "")
S3_BUCKET = os.environ.get("LANCE_E2E_S3_BUCKET", "lance-catalog")
S3_ACCESS_KEY = os.environ.get("LANCE_E2E_S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("LANCE_E2E_S3_SECRET_KEY", "")

WAREHOUSE = "warehouse:lance_catalog"
GOLD_VALIDATOR = {"user": "user:service-silver-to-gold", "relation": "validator", "object": "namespace:gold"}
#: stage operation names (chart values) — each stage's run id is uuid5-derived from "<operation>-<token>".
OPERATIONS = ("lance_ray_ingest", "ingest_events", "embed_features", "aggregate_gold")

pytestmark = [pytest.mark.e2e, pytest.mark.governed_union]


# --------------------------------------------------------------------------- #
# stack plumbing
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def stack() -> tuple[str, str]:
    if not (LANCERAY and LINEAGE and FGA):
        pytest.skip("set LANCE_E2E_LANCERAY_URL / LANCE_E2E_LINEAGE_URL / LANCE_E2E_FGA (see docstring)")
    for name, url in (("lance-ray", LANCERAY), ("lineage", LINEAGE)):
        try:
            requests.get(f"{url.rstrip('/')}/livez", timeout=5).raise_for_status()
        except Exception:  # noqa: BLE001
            pytest.skip(f"{name} not reachable at {url}")
    try:
        requests.get(f"{DEX}/.well-known/openid-configuration", timeout=5).raise_for_status()
        requests.get(f"{FGA}/healthz", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip("dex / openfga not reachable")
    # The whole point is the GOVERNED union — on an auth-off stack these assertions would prove nothing,
    # so detect it (an anonymous /runs read succeeding == lineage auth is off) and skip loudly.
    if requests.get(f"{LINEAGE.rstrip('/')}/runs", timeout=8).status_code != 401:
        pytest.skip("stack is not auth-on (anonymous /runs succeeded) — deploy the union per the docstring")
    return LANCERAY.rstrip("/"), LINEAGE.rstrip("/")


@pytest.fixture(scope="module")
def fga_store() -> tuple[str, str]:
    """The lance-catalog OpenFGA store + latest authorization model id (raw HTTP, like the services)."""
    stores = requests.get(f"{FGA}/stores", timeout=10).json()["stores"]
    store = next(s["id"] for s in stores if s["name"] == "lance-catalog")
    models = requests.get(f"{FGA}/stores/{store}/authorization-models", timeout=10).json()
    return store, models["authorization_models"][0]["id"]


def _tuples(
    fga_store: tuple[str, str], *, writes: list[dict] | None = None, deletes: list[dict] | None = None
) -> None:
    """Write/delete tuples via OpenFGA's Write RPC, idempotently across runs.

    Only the two IDEMPOTENCY 400s are tolerated (duplicate write / delete-of-absent — matched on the
    error message); any other 400 (malformed tuple, bad relation, wrong model id) fails HERE with the
    real error, not 90 seconds later as a misleading poll timeout (audit: a blanket 400-pass masked
    real seed errors)."""
    store, model = fga_store
    body: dict = {"authorization_model_id": model}
    if writes:
        body["writes"] = {"tuple_keys": writes}
    if deletes:
        body["deletes"] = {"tuple_keys": deletes}
    resp = requests.post(f"{FGA}/stores/{store}/write", json=body, timeout=10)
    if resp.status_code == 200:
        return
    message = resp.json().get("message", "") if resp.status_code == 400 else ""
    assert "already exists" in message or "did not exist" in message or "does not exist" in message, (
        f"OpenFGA write failed ({resp.status_code}): {resp.text}"
    )


def _token(username: str) -> str:
    data = {
        "grant_type": "password",
        "client_id": "lance-catalog",
        "username": username,
        "password": "password",
        "scope": "openid",
    }
    if DEX_SECRET:
        data["client_secret"] = DEX_SECRET
    body = requests.post(f"{DEX}/token", data=data, timeout=10).json()
    assert "id_token" in body, f"Dex token grant failed: {body}"
    return body["id_token"]


def _sub(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


@pytest.fixture(scope="module")
def alice(stack: tuple[str, str], fga_store: tuple[str, str]) -> dict[str, str]:
    """An authenticated READER over the medallion estate: warehouse reader + the seed script's
    table→namespace parent links give her can_get_metadata on every cascade dataset."""
    token = _token("alice@example.com")
    _tuples(fga_store, writes=[{"user": f"user:{_sub(token)}", "relation": "reader", "object": WAREHOUSE}])
    return {"Authorization": f"Bearer {token}"}


def _run_id_for(operation: str, token: str) -> str:
    """The deterministic per-stage run id — uuid5 over "<operation>-<token>", the producer's own scheme
    (common.openlineage.run_id_for), so one /produce token names every stage run it caused."""
    from common.openlineage import run_id_for

    return run_id_for(f"{operation}-{token}")


def _run_states(lineage: str, headers: dict[str, str]) -> dict[str, str]:
    resp = requests.get(f"{lineage}/runs?limit=1000", headers=headers, timeout=8)
    resp.raise_for_status()
    return {r["run_id"]: r.get("state") or "" for r in resp.json().get("runs", [])}


def _producer_for(lineage: str, headers: dict[str, str], dataset: str, run_id: str) -> dict | None:
    resp = requests.get(f"{lineage}/datasets/{dataset}/producers", headers=headers, timeout=8)
    if resp.status_code != 200:
        return None
    return next((p for p in resp.json().get("producers", []) if p["run_id"] == run_id), None)


def _poll(predicate: Callable[[], bool], *, timeout: float = 90.0, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(3)
    pytest.fail(message)


def _produce(lance_ray: str) -> str:
    resp = requests.post(f"{lance_ray}/produce", headers={"dapr-api-token": DAPR_TOKEN}, timeout=30)
    assert resp.status_code == 202, resp.text
    return resp.json()["token"]


# --------------------------------------------------------------------------- #
# 1. governed ALLOW — the full union works, and the same stack really enforces
# --------------------------------------------------------------------------- #


def test_governed_allow_full_cascade_with_quality_verdicts(
    stack: tuple[str, str], alice: dict[str, str]
) -> None:
    lance_ray, lineage = stack
    token = _produce(lance_ray)
    rids = {op: _run_id_for(op, token) for op in OPERATIONS}

    # All four stage runs land COMPLETE under the seeded service grants — correlated to THIS drive by the
    # deterministic run ids (not by counts), so a stale graph can't false-pass.
    _poll(
        lambda: all(_run_states(lineage, alice).get(rid) == "COMPLETE" for rid in rids.values()),
        message=f"governed cascade did not complete for token {token}: "
        f"{ {op: _run_states(lineage, alice).get(rid) for op, rid in rids.items()} }",
    )

    # The quality gate ran on real compute output and recorded its verdict on the WROTE edge.
    silver = _producer_for(lineage, alice, "silver$features", rids["embed_features"])
    assert silver is not None
    assert silver["row_count"], f"no measured rows — is medallion.compute on? {silver}"
    assert silver["quality_passed"] is True, silver
    assert {a["assertion"] for a in silver["quality_assertions"]} == {"row_count_positive", "not_null"}

    # Governance is live in the SAME stack: anonymous read 401s; an ungranted user 403s on the route gate.
    assert requests.get(f"{lineage}/runs", timeout=8).status_code == 401
    bob = {"Authorization": f"Bearer {_token('bob@example.com')}"}
    denied = requests.get(f"{lineage}/datasets/gold$catalog/upstream", headers=bob, timeout=8)
    assert denied.status_code == 403, denied.text


# --------------------------------------------------------------------------- #
# 2. FGA-deny → DROP, live: revoke the gold validator, the cascade stops at silver
# --------------------------------------------------------------------------- #


def test_fga_deny_drops_gold_promotion_and_regrant_restores(
    stack: tuple[str, str], alice: dict[str, str], fga_store: tuple[str, str]
) -> None:
    lance_ray, lineage = stack
    _tuples(fga_store, deletes=[GOLD_VALIDATOR])
    try:
        token = _produce(lance_ray)
        silver_rid = _run_id_for("embed_features", token)
        gold_rid = _run_id_for("aggregate_gold", token)

        # The cascade reaches silver (writers still granted) …
        _poll(
            lambda: _run_states(lineage, alice).get(silver_rid) == "COMPLETE",
            message=f"silver never completed for deny-drive token {token}",
        )
        # … and the silver→gold mover, denied can_promote, DROPs BEFORE any emit: gold's run never lands.
        # (The deny is instant relative to the silver COMPLETE we just observed — the trigger was already
        # delivered — but give redelivery windows a grace period before asserting the negative.)
        time.sleep(12)
        assert _run_states(lineage, alice).get(gold_rid) is None, (
            f"gold run {gold_rid} appeared despite the revoked validator tuple — FGA gate NOT enforcing"
        )
    finally:
        _tuples(fga_store, writes=[GOLD_VALIDATOR])  # restore even if the assert above fails

    # Positive control: with the tuple back, the next drive cascades to gold — the tuple was the only delta.
    token2 = _produce(lance_ray)
    gold2 = _run_id_for("aggregate_gold", token2)
    _poll(
        lambda: _run_states(lineage, alice).get(gold2) == "COMPLETE",
        message=f"gold did not cascade after re-granting the validator (token {token2})",
    )


# --------------------------------------------------------------------------- #
# 3. quality-block, live: a bad batch derives into silver, is recorded, and never reaches gold
# --------------------------------------------------------------------------- #


def test_quality_gate_blocks_bad_batch_and_records_verdict(
    stack: tuple[str, str], alice: dict[str, str]
) -> None:
    if not (MOVER_URL and S3_ENDPOINT and S3_ACCESS_KEY and S3_SECRET_KEY):
        pytest.skip("set LANCE_E2E_MOVER_URL + LANCE_E2E_S3_* for the quality-block drive")
    import lance
    import pyarrow as pa

    lance_ray, lineage = stack
    opts = {
        "endpoint": S3_ENDPOINT,
        "access_key_id": S3_ACCESS_KEY,
        "secret_access_key": S3_SECRET_KEY,
        "region": "us-east-1",
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
    }
    bronze_uri = f"s3://{S3_BUCKET}/medallion/bronze"

    # Corrupt bronze IN PLACE (same schema, ids nulled) — the shape of an upstream writer landing a bad
    # batch that lineage-side governance can't see coming.
    table = lance.dataset(bronze_uri, storage_options=opts).to_table()
    id_field = table.schema.field("id")
    bad = table.set_column(table.schema.get_field_index("id"), id_field, pa.nulls(len(table), id_field.type))
    lance.write_dataset(bad, bronze_uri, mode="overwrite", storage_options=opts)

    # Deliver the stage trigger exactly as the sidecar would (same route, same app-token guard).
    token = uuid.uuid4().hex[:12]
    resp = requests.post(
        f"{MOVER_URL.rstrip('/')}/medallion-event",
        json={"data": {"token": token, "dataset": "bronze$events", "namespace": "bronze"}},
        headers={"dapr-api-token": MOVER_TOKEN},
        timeout=180,
    )
    assert resp.status_code == 200 and resp.json()["status"] == "DROP", resp.text  # blocked, not cascaded

    # The blocked batch is fully auditable in lineage: the run COMPLETEd (the write happened), the gate
    # verdict rides the WROTE edge — quality_passed false with the failed not_null(id) assertion.
    silver_rid = _run_id_for("embed_features", token)
    _poll(
        lambda: (
            (_producer_for(lineage, alice, "silver$features", silver_rid) or {}).get("quality_passed")
            is False
        ),
        message=f"blocked-batch verdict never appeared on silver$features for token {token}",
    )
    entry = _producer_for(lineage, alice, "silver$features", silver_rid)
    assert entry is not None
    not_null = next(a for a in entry["quality_assertions"] if a["assertion"] == "not_null")
    assert not_null["success"] is False and not_null["column"] == "id"

    # And the bad batch never promoted: no gold run for this token (grace period for the negative).
    time.sleep(12)
    assert _run_states(lineage, alice).get(_run_id_for("aggregate_gold", token)) is None

    # Restore: a fresh /produce overwrites the corrupted bronze and cascades clean data through to gold.
    token2 = _produce(lance_ray)
    gold2 = _run_id_for("aggregate_gold", token2)
    _poll(
        lambda: _run_states(lineage, alice).get(gold2) == "COMPLETE",
        message=f"cascade did not recover after the quality-block drive (token {token2})",
    )


# --------------------------------------------------------------------------- #
# 4. MEDIA lane under governance — blobs land + artifacts derive with the seeded grants
# --------------------------------------------------------------------------- #


def test_media_lane_derives_under_governance(stack: tuple[str, str], alice: dict[str, str]) -> None:
    lance_ray, lineage = stack
    resp = requests.post(f"{lance_ray}/ingest-media", headers={"dapr-api-token": DAPR_TOKEN}, timeout=60)
    if resp.status_code == 409:
        pytest.skip("media head not configured (medallion.compute off on this stack)")
    assert resp.status_code == 202, resp.text
    token = resp.json()["token"]

    ingest_rid = _run_id_for("ingest_media", token)
    derive_rid = _run_id_for("derive_media", token)
    _poll(
        lambda: (
            _run_states(lineage, alice).get(ingest_rid) == "COMPLETE"
            and _run_states(lineage, alice).get(derive_rid) == "COMPLETE"
        ),
        message=f"governed media lane did not flow for token {token}",
    )

    # Derived artifacts, read back through the GOVERNED schema endpoint (alice's grant, not an open route).
    schema = requests.get(f"{lineage}/datasets/silver-media$features/schema", headers=alice, timeout=8)
    schema.raise_for_status()
    fields = {f["name"]: f["type"] for f in schema.json().get("fields", [])}
    assert "thumbnail" in fields and "embedding" in fields, fields
    assert fields["payload"] == "blob"

    # Provenance under governance: silver-media ← bronze-media (both granted via the seeded parent links).
    upstream = requests.get(f"{lineage}/datasets/silver-media$features/upstream", headers=alice, timeout=8)
    upstream.raise_for_status()
    assert "bronze-media$objects" in {d["name"] for d in upstream.json().get("related", [])}
    # The external s3:// SOURCE objects are recorded in the graph (the auth-off media e2e asserts their
    # presence) but alice holds no grant on them — the transitive-disclosure filter must DROP them from
    # her governed view rather than leak external-source names through a related-datasets side channel.
    sources = requests.get(f"{lineage}/datasets/bronze-media$objects/upstream", headers=alice, timeout=8)
    sources.raise_for_status()
    assert not any(d["name"].startswith("s3://") for d in sources.json().get("related", []))

    # An ungranted user cannot see any of it — the media estate is governed like the rest.
    bob = {"Authorization": f"Bearer {_token('bob@example.com')}"}
    assert (
        requests.get(f"{lineage}/datasets/silver-media$features/schema", headers=bob, timeout=8).status_code
        == 403
    )
