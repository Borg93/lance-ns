"""OpenFGA authorization wiring tests (our logic only — fga IO is faked).

These assert *our* authz layer end to end through the router-level ``authorize``
dependency and the per-endpoint tuple seeding / list filtering — the OpenFGA SDK
calls (``check`` / ``batch_check`` / ``list_objects`` / ``write_tuples`` via
``grant_on_create``) are faked so nothing leaves the process. The pure id helpers
(``canonical_object_id`` / ``parent_namespace_id``) run for real so the grant path
and the check path are proven to agree byte-for-byte.

Each test names the CONTRACT it pins, so a reviewer can catch a mismatch if another
agent's design drifts. The app checks ``can_*`` ACTION relations (the model owns the
op->privilege mapping); each ``can_*`` reduces to a reader/writer/owner rung in the
model. The contracts asserted here (owned by the fga / fga_deps / endpoint agents) are:

* Op -> ``can_*``: reads -> ``can_get_metadata`` / ``can_read_data`` (reader rung);
  generic mutations -> ``can_write_data`` (writer rung); lifecycle/destructive
  (``drop`` / ``deregister`` / namespace ``drop``) -> ``can_drop`` / ``can_deregister`` /
  ``can_delete`` (owner rung).
* Create-on-parent: ``create`` / ``declare`` / ``register`` of a *child* is authorized
  against the PARENT (``can_create_table`` / ``can_create_namespace``), never the
  not-yet-existing child; tuples are seeded AFTER a successful create via
  ``fga.grant_on_create`` — which now links every created object to its ``parent`` so
  the concentric cascade reaches it (nested namespaces included).
* Batch routes (``/v1/table/version/batch-create``, ``/v1/table/batch-commit``)
  and ``transaction`` / ``materialized_view`` routes require authz, not authn-only.
  Destructive batch ops use the owner tier (no writer back-door).
* Fail-closed: FGA enabled but no ``app.state.fga`` client -> 503 (never allow).
* ``GET /v1/table`` is filtered to the tables the caller can read via ``list_objects``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from catalog.core.config import Settings, get_settings
from common import fga as fga_module
from common.oidc import IDToken
from fastapi.testclient import TestClient
from lance_namespace import (
    CreateNamespaceResponse,
    CreateTableResponse,
    DeclareTableResponse,
    DeregisterTableResponse,
    DescribeTableResponse,
    DropNamespaceResponse,
    DropTableResponse,
    ListTablesResponse,
    RenameTableResponse,
)

ARROW_STREAM = {"content-type": "application/vnd.apache.arrow.stream"}


def _auth_settings() -> Settings:
    # model_validate (not Settings(...)) so field-name keys validate cleanly: the
    # fields carry LANCE_* aliases and populate_by_name accepts the names at runtime.
    return Settings.model_validate(
        {
            "oidc_enabled": True,
            "oidc_issuer": "https://idp.example",
            "oidc_audience": "lance",
            "fga_enabled": True,
            "fga_api_url": "http://openfga:8080",
            "s3_access_key_id": "x",
            "s3_secret_access_key": "x",
        }
    )


def _wire(client: TestClient) -> MagicMock:
    """Enable OIDC+FGA, inject a faked verifier + a sentinel FGA client.

    The verifier returns user ``alice``; the FGA client is a sentinel that the faked
    ``fga.*`` functions ignore. Returns the sentinel so a test can drop it (fail-closed).
    """
    client.app.dependency_overrides[get_settings] = _auth_settings
    verifier = MagicMock()
    verifier.verify.return_value = IDToken(iss="i", sub="alice", aud="lance", exp=1, iat=1)
    client.app.state.oidc = verifier
    fga_client = MagicMock()  # sentinel; the faked fga.* functions below ignore it
    fga_client.close = AsyncMock()  # closed by the lifespan on shutdown
    client.app.state.fga = fga_client
    return fga_client


def _fake_check(captured: list[dict], *, allow: bool):
    async def fake_check(_client: object, *, user: str, relation: str, obj: str, **_kw: object) -> bool:
        captured.append({"user": user, "relation": relation, "obj": obj})
        return allow

    return fake_check


# --------------------------------------------------------------------------- #
# Relation tiers: reader / writer / owner.
# --------------------------------------------------------------------------- #


def test_read_op_checks_reader_and_allows(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a read op (describe) checks ``can_get_metadata`` (reader rung) and allows."""
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=True))

    resp = client.post("/v1/table/db1$users/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert captured == [{"user": "alice", "relation": "can_get_metadata", "obj": "table:db1$users"}]


def test_generic_mutation_checks_writer(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a non-lifecycle mutation (rename) checks ``can_write_data`` (writer rung)."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post(
        "/v1/table/db1$users/rename",
        json={"new_table_name": "u2"},
        headers={"Authorization": "Bearer t"},
    )
    assert resp.status_code == 403
    assert captured[-1] == {"user": "alice", "relation": "can_write_data", "obj": "table:db1$users"}


def test_drop_table_requires_owner_and_403_is_problem_json(client: TestClient, monkeypatch) -> None:
    """CONTRACT: dropping a table requires the owner tier via ``can_drop``, 403 -> problem+json.

    NOTE: this supersedes the old behaviour where ``drop`` mapped to ``writer``. Per
    ``design-permissions.md`` (``can_drop: owner``), destructive ops require ``owner``.
    """
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post("/v1/table/db1$users/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == 15  # PERMISSION_DENIED
    assert captured[-1] == {"user": "alice", "relation": "can_drop", "obj": "table:db1$users"}


def test_deregister_table_requires_owner(client: TestClient, monkeypatch) -> None:
    """CONTRACT: ``deregister`` is also owner-tier, via ``can_deregister``."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post("/v1/table/db1$users/deregister", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured[-1]["relation"] == "can_deregister"
    assert captured[-1]["obj"] == "table:db1$users"


def test_drop_namespace_requires_owner_on_namespace_object(client: TestClient, monkeypatch) -> None:
    """CONTRACT: dropping a namespace is owner-tier via ``can_delete`` on the ``namespace:`` object."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post("/v1/namespace/db1/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured[-1] == {"user": "alice", "relation": "can_delete", "obj": "namespace:db1"}


# --------------------------------------------------------------------------- #
# Create-on-parent: authorize the parent, then seed owner + parent tuples.
# --------------------------------------------------------------------------- #


def test_create_table_checks_writer_on_parent_namespace(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: creating ``db1$users`` checks ``can_create_table`` on PARENT ``namespace:db1``.

    The leaf table does not exist yet, so the check is on the parent (create-on-parent).
    """
    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=1)
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post(
        "/v1/table/db1$users/create",
        content=b"ARROW",
        headers={"Authorization": "Bearer t", **ARROW_STREAM},
    )
    assert resp.status_code == 403
    assert captured[-1] == {"user": "alice", "relation": "can_create_table", "obj": "namespace:db1"}


def test_create_table_seeds_owner_and_parent_tuples(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: a successful create seeds ``owner`` on the table + a ``parent`` link.

    Seeding goes through the single write path ``fga.grant_on_create`` AFTER the backend
    create succeeds. We assert the args it receives (resource/obj_id/parent) — the real
    ``canonical_object_id`` / ``parent_namespace_id`` helpers run, proving the grant id
    (``table:db1$users``, parent ``db1``) matches what ``authorize`` would later check.
    """
    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=1)
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    grant = AsyncMock()
    monkeypatch.setattr(fga_module, "grant_on_create", grant)

    resp = client.post(
        "/v1/table/db1$users/create",
        content=b"ARROW",
        headers={"Authorization": "Bearer t", **ARROW_STREAM},
    )
    assert resp.status_code == 200
    grant.assert_awaited_once()
    call = grant.await_args
    assert call is not None
    kwargs = call.kwargs
    assert kwargs["user_sub"] == "alice"
    assert kwargs["resource"] == "table"
    assert kwargs["obj_id"] == "db1$users"  # canonical delimited id
    assert kwargs["parent_object"] == "namespace:db1"  # parent link of db1$users


def test_create_table_does_not_seed_when_backend_fails(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: no tuples are seeded if the backend create raises (no orphan grant)."""
    from lance_namespace import TableAlreadyExistsError

    fake_ns.create_table.side_effect = TableAlreadyExistsError("exists")
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    grant = AsyncMock()
    monkeypatch.setattr(fga_module, "grant_on_create", grant)

    resp = client.post(
        "/v1/table/db1$users/create",
        content=b"ARROW",
        headers={"Authorization": "Bearer t", **ARROW_STREAM},
    )
    assert resp.status_code == 409
    grant.assert_not_awaited()


def test_declare_table_is_create_on_parent(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: ``declare`` is also create-on-parent — checks ``can_create_table`` on parent."""
    fake_ns.declare_table.return_value = DeclareTableResponse()
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post("/v1/table/db1$users/declare", json={}, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured[-1] == {"user": "alice", "relation": "can_create_table", "obj": "namespace:db1"}


def test_create_namespace_seeds_owner_and_parent_link(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: creating a nested namespace checks ``can_create_namespace`` on its parent,
    then seeds an ``owner`` tuple AND a ``parent`` link to the parent namespace — so an
    owner of ``parent`` cascades into ``parent$child`` and all its tables (no lockout)."""
    fake_ns.create_namespace.return_value = CreateNamespaceResponse(properties={})
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=True))
    grant = AsyncMock()
    monkeypatch.setattr(fga_module, "grant_on_create", grant)

    resp = client.post("/v1/namespace/parent$child/create", json={}, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    # authorize() checked can_create_namespace on the parent namespace, not the child.
    assert captured[-1] == {"user": "alice", "relation": "can_create_namespace", "obj": "namespace:parent"}
    grant.assert_awaited_once()
    call = grant.await_args
    assert call is not None
    kwargs = call.kwargs
    assert kwargs["resource"] == "namespace"
    assert kwargs["obj_id"] == "parent$child"
    assert kwargs["parent_object"] == "namespace:parent"  # nested ns links to its parent


def test_create_top_level_namespace_links_to_catalog_root(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: a TOP-LEVEL namespace seeds its ``parent`` as the FGA root object (the warehouse
    root), so a warehouse-/project-level grant cascades into it."""
    fake_ns.create_namespace.return_value = CreateNamespaceResponse(properties={})
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    grant = AsyncMock()
    monkeypatch.setattr(fga_module, "grant_on_create", grant)

    resp = client.post("/v1/namespace/bronze/create", json={}, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    call = grant.await_args
    assert call is not None
    kwargs = call.kwargs
    assert kwargs["obj_id"] == "bronze"
    assert kwargs["parent_object"] == "warehouse:lance_catalog"  # default fga_root_object


# --------------------------------------------------------------------------- #
# Revoke-on-delete: a successful lifecycle op CLEANS UP the object's FGA tuples.
# These guard the WIRING — deleting the revoke call in tables.py/namespaces.py
# (re-opening the stale-grant bleed) must turn these red. The deny-path tests above
# never reach the endpoint body, so they can't catch a missing revoke.
# --------------------------------------------------------------------------- #


def test_drop_table_revokes_tuples(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a successful drop_table revokes the table's tuples (obj ``table:db1$users``)."""
    fake_ns.drop_table.return_value = DropTableResponse()
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(fga_module, "revoke_object_tuples", revoke)

    resp = client.post("/v1/table/db1$users/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    revoke.assert_awaited_once()
    call = revoke.await_args
    assert call is not None and call.args[1] == "table:db1$users"


def test_deregister_table_revokes_tuples(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a successful deregister_table revokes the table's tuples."""
    fake_ns.deregister_table.return_value = DeregisterTableResponse()
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(fga_module, "revoke_object_tuples", revoke)

    resp = client.post("/v1/table/db1$users/deregister", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    revoke.assert_awaited_once()
    call = revoke.await_args
    assert call is not None and call.args[1] == "table:db1$users"


def test_drop_namespace_revokes_tuples(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a successful drop_namespace revokes the namespace's tuples (obj ``namespace:db1``)."""
    fake_ns.drop_namespace.return_value = DropNamespaceResponse()
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(fga_module, "revoke_object_tuples", revoke)

    resp = client.post("/v1/namespace/db1/drop", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    revoke.assert_awaited_once()
    call = revoke.await_args
    assert call is not None and call.args[1] == "namespace:db1"


def test_rename_table_revokes_source_then_seeds_destination(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: rename revokes the SOURCE id's tuples and seeds the DEST — and revoke fires BEFORE seed,
    so no stale grant survives under the old id (``table:db1$users``) while the dest (``db1$u2``) is owned."""
    fake_ns.rename_table.return_value = RenameTableResponse()
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=True))
    order: list[str] = []

    async def _revoke(_c: object, obj: str, **_k: object) -> int:
        order.append(f"revoke:{obj}")
        return 1

    async def _grant(_c: object, **kw: object) -> None:
        order.append(f"grant:{kw['obj_id']}")

    monkeypatch.setattr(fga_module, "revoke_object_tuples", _revoke)
    monkeypatch.setattr(fga_module, "grant_on_create", _grant)

    resp = client.post(
        "/v1/table/db1$users/rename",
        json={"new_table_name": "u2"},
        headers={"Authorization": "Bearer t"},
    )
    assert resp.status_code == 200
    assert order == ["revoke:table:db1$users", "grant:db1$u2"]


# --------------------------------------------------------------------------- #
# Batch + transaction + materialized_view: authz, not authn-only.
# --------------------------------------------------------------------------- #


def test_batch_commit_requires_writer_on_each_table(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: ``/v1/table/batch-commit`` requires ``can_write_data`` on every table named
    in the body (via ``batch_check``); a denial on any one is 403. Previously authn-only."""
    _wire(client)
    seen: dict = {}

    async def fake_batch_check(
        _c: object, *, user: str, relation: str, objects: list[str]
    ) -> dict[str, bool]:
        seen.update(user=user, relation=relation, objects=list(objects))
        # Deny db1$b to prove a single denial fails the whole batch.
        return {o: (o != "table:db1$b") for o in objects}

    monkeypatch.setattr(fga_module, "batch_check", fake_batch_check)

    body = {
        "operations": [
            {"create_table_version": {"id": ["db1", "a"]}},
            {"create_table_version": {"id": ["db1", "b"]}},
        ]
    }
    resp = client.post("/v1/table/batch-commit", json=body, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert seen["relation"] == "can_write_data"
    assert set(seen["objects"]) == {"table:db1$a", "table:db1$b"}


def test_batch_commit_deregister_requires_owner_tier(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: a destructive op inside batch-commit (``deregister_table``) is checked at the
    OWNER tier via ``can_deregister`` — closing the writer back-door the audit flagged."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    body = {"operations": [{"deregister_table": {"id": ["db1", "a"]}}]}
    resp = client.post("/v1/table/batch-commit", json=body, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured[-1] == {"user": "alice", "relation": "can_deregister", "obj": "table:db1$a"}


def test_batch_malformed_body_fails_closed(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a malformed batch body (``operations`` not a list) is a 403 deny, never a
    500 crash or a silently-skipped check. The security gate must fail closed on bad input."""
    _wire(client)

    async def boom(*_a: object, **_k: object) -> dict[str, bool]:
        raise AssertionError("batch_check must not run on a malformed body")

    monkeypatch.setattr(fga_module, "batch_check", boom)

    resp = client.post(
        "/v1/table/batch-commit", json={"operations": 42}, headers={"Authorization": "Bearer t"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 15  # PERMISSION_DENIED, not a 500


def test_batch_create_versions_requires_writer(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: ``/v1/table/version/batch-create`` requires ``can_write_data`` on each entry."""
    _wire(client)
    seen: dict = {}

    async def fake_batch_check(
        _c: object, *, user: str, relation: str, objects: list[str]
    ) -> dict[str, bool]:
        seen.update(relation=relation, objects=list(objects))
        return dict.fromkeys(objects, False)

    monkeypatch.setattr(fga_module, "batch_check", fake_batch_check)

    body = {"entries": [{"id": ["db1", "users"]}]}
    resp = client.post("/v1/table/version/batch-create", json=body, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert seen["relation"] == "can_write_data"
    assert seen["objects"] == ["table:db1$users"]


def test_transaction_route_requires_authz(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: a transaction op is authorized (scoped to the ``table`` FGA type for now),
    not merely authenticated. A denial is 403."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post("/v1/transaction/txn1/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 403
    assert captured, "transaction route must run an authz check, not pass on authn only"
    assert captured[-1]["obj"] == "table:txn1"  # transaction scoped to table type
    assert captured[-1]["relation"] == "can_get_metadata"  # describe is a read op


def test_materialized_view_create_is_create_on_parent(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    """CONTRACT: creating a materialized view is authorized (create-on-parent), not
    authn-only. Scoped to the ``table`` FGA type; the check is on the parent namespace."""
    _wire(client)
    captured: list[dict] = []
    monkeypatch.setattr(fga_module, "check", _fake_check(captured, allow=False))

    resp = client.post(
        "/v1/materialized_view/db1$mv/create",
        json={"query": "select 1", "view_name": "mv"},
        headers={"Authorization": "Bearer t"},
    )
    assert resp.status_code == 403
    assert captured, "materialized_view create must run an authz check"
    assert captured[-1]["relation"] == "can_create_table"
    assert captured[-1]["obj"] == "namespace:db1"  # create-on-parent
    # NOTE: the post-create owner+parent seeding (the audit's deny-all-on-own-MV fix) uses the
    # same fga.grant_on_create path proven by test_create_table_seeds_owner_and_parent_tuples;
    # a dedicated success-path test is omitted only because CreateMaterializedViewRequest needs
    # a full Arrow output_schema body to get past validation.


# --------------------------------------------------------------------------- #
# Fail-closed: enabled FGA but no client -> 503, never allow.
# --------------------------------------------------------------------------- #


def test_fail_closed_when_fga_client_missing(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: FGA enabled but ``app.state.fga`` absent -> 503 (never silently allow)."""
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    _wire(client)
    # Simulate an unwired client (e.g. lifespan provisioning failed).
    if hasattr(client.app.state, "fga"):
        delattr(client.app.state, "fga")

    # check must never even be reached.
    def boom(*_a: object, **_k: object):
        raise AssertionError("fga.check must not be called when the client is missing")

    monkeypatch.setattr(fga_module, "check", boom)

    resp = client.post("/v1/table/db1$users/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == 17  # SERVICE_UNAVAILABLE


def test_fail_closed_when_openfga_outage(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: an OpenFGA outage surfaces as 503 (fga.check raises ServiceUnavailableError),
    never as an allow. Asserts the fail-closed posture of fga.check propagates to the route."""
    from lance_namespace import ServiceUnavailableError

    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    _wire(client)

    async def outage(*_a: object, **_k: object) -> bool:
        raise ServiceUnavailableError("authorization service unavailable")

    monkeypatch.setattr(fga_module, "check", outage)

    resp = client.post("/v1/table/db1$users/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 503
    assert resp.json()["code"] == 17  # SERVICE_UNAVAILABLE


def test_authn_still_required_when_fga_enabled(client: TestClient, monkeypatch) -> None:
    """CONTRACT: with FGA on, a missing token is 401 (authn) before any authz check runs."""
    _wire(client)

    def boom(*_a: object, **_k: object):
        raise AssertionError("authz must not run before authentication")

    monkeypatch.setattr(fga_module, "check", boom)

    resp = client.post("/v1/table/db1$users/drop")  # no Authorization header
    assert resp.status_code == 401
    assert resp.json()["code"] == 16  # UNAUTHENTICATED


# --------------------------------------------------------------------------- #
# List filtering via list_objects.
# --------------------------------------------------------------------------- #


def test_list_tables_filtered_by_list_objects(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    """CONTRACT: ``GET /v1/table`` returns only tables the caller can read, intersected with
    the backend listing using ``fga.list_objects(relation='can_read_data', type='table')``."""
    fake_ns.list_all_tables.return_value = ListTablesResponse(tables=["users", "orders", "secret"])
    _wire(client)
    seen: dict = {}

    async def fake_list_objects(_c: object, *, user: str, relation: str, object_type: str) -> list[str]:
        seen.update(user=user, relation=relation, object_type=object_type)
        # Caller can read users + orders (and some table not in this listing).
        return ["table:users", "table:orders", "table:elsewhere"]

    monkeypatch.setattr(fga_module, "list_objects", fake_list_objects)

    resp = client.get("/v1/table", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert resp.json()["tables"] == ["users", "orders"]  # secret filtered out
    assert seen == {"user": "alice", "relation": "can_read_data", "object_type": "table"}


def test_list_tables_unfiltered_when_fga_disabled(client: TestClient, fake_ns: MagicMock) -> None:
    """CONTRACT: with FGA disabled the listing is returned verbatim (no filtering)."""
    fake_ns.list_all_tables.return_value = ListTablesResponse(tables=["users", "orders"])
    # default settings: oidc/fga disabled
    resp = client.get("/v1/table")
    assert resp.status_code == 200
    assert resp.json()["tables"] == ["users", "orders"]


@pytest.mark.parametrize("allow", [True, False])
def test_describe_allow_and_deny(client: TestClient, fake_ns: MagicMock, monkeypatch, allow: bool) -> None:
    """CONTRACT: a positive check lets the request through (200); a negative one is 403."""
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    _wire(client)
    monkeypatch.setattr(fga_module, "check", _fake_check([], allow=allow))

    resp = client.post("/v1/table/db1$users/describe", headers={"Authorization": "Bearer t"})
    assert resp.status_code == (200 if allow else 403)
