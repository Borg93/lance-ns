"""Integration tests for *our* REST layer.

The namespace backend is faked, so every assertion is about code we wrote:
identifier parsing from the path, routing to the correct operation, request
assembly (query params / headers / body), response serialization and
content-types, and error → HTTP / Problem-Details mapping. No lance operations
are exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pyarrow as pa
from fastapi.testclient import TestClient
from lance_namespace import (
    BatchDeleteTableVersionsResponse,
    CreateNamespaceResponse,
    CreateTableResponse,
    CreateTableVersionResponse,
    DescribeTableResponse,
    DescribeTableVersionResponse,
    ListNamespacesResponse,
    ListTableVersionsResponse,
    MergeInsertIntoTableResponse,
    TableAlreadyExistsError,
    TableNotFoundError,
    TableVersion,
    TableVersionNotFoundError,
)

ARROW_STREAM = {"content-type": "application/vnd.apache.arrow.stream"}


# --- identifier parsing (our logic) ---------------------------------------- #


def test_table_id_is_parsed_from_path(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    client.post("/v1/table/db1$users/describe")
    assert fake_ns.describe_table.call_args.args[0].id == ["db1", "users"]


def test_root_namespace_id_is_empty_list(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.list_namespaces.return_value = ListNamespacesResponse(namespaces=["a"])
    client.get("/v1/namespace/$/list")
    assert fake_ns.list_namespaces.call_args.args[0].id == []


def test_create_namespace_routes_with_body_and_id(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.create_namespace.return_value = CreateNamespaceResponse(properties={"team": "ml"})
    resp = client.post("/v1/namespace/parent$child/create", json={"properties": {"team": "ml"}})
    assert resp.status_code == 200
    req = fake_ns.create_namespace.call_args.args[0]
    assert req.id == ["parent", "child"]
    assert req.properties == {"team": "ml"}
    assert resp.json() == {"properties": {"team": "ml"}}  # our serialization


# --- query-param / header assembly (our logic) ----------------------------- #


def test_describe_table_maps_query_params(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.describe_table.return_value = DescribeTableResponse(location="s3://x")
    client.post("/v1/table/db$t/describe?with_table_uri=true&load_detailed_metadata=true")
    req = fake_ns.describe_table.call_args.args[0]
    assert req.with_table_uri is True
    assert req.load_detailed_metadata is True


def test_create_table_passes_arrow_bytes_through(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=1)
    client.post("/v1/table/db$t/create?mode=overwrite", content=b"ARROWSTREAM", headers=ARROW_STREAM)
    req, data = fake_ns.create_table.call_args.args
    assert req.id == ["db", "t"]
    assert req.mode == "overwrite"
    assert data == b"ARROWSTREAM"  # our raw-body passthrough


def test_create_table_accepts_spec_properties_query_param(client: TestClient, fake_ns: MagicMock) -> None:
    # Spec 0.9 passes properties as a JSON-encoded query param (no header form).
    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=1)
    client.post('/v1/table/db$t/create?properties={"team":"eng"}', content=b"A", headers=ARROW_STREAM)
    req, _ = fake_ns.create_table.call_args.args
    assert req.properties == {"team": "eng"}


def _arrow_ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def test_create_strips_root_storage_options_from_response(client: TestClient, fake_ns: MagicMock) -> None:
    # #88: the native backend echoes the catalog's ROOT storage creds; the create response must NOT carry
    # them (storage access is vended only via /credentials).
    fake_ns.create_table.return_value = CreateTableResponse(
        location="s3://x",
        version=1,
        storage_options={"access_key_id": "rustfsadmin", "secret_access_key": "rustfsadmin"},
    )
    body = _arrow_ipc(pa.table({"id": [1]}))
    resp = client.post("/v1/table/db$t/create", content=body, headers=ARROW_STREAM)

    assert resp.status_code == 200
    assert "storage_options" not in resp.json()
    assert "rustfsadmin" not in resp.text


def test_create_delegates_to_dataplane_create_table(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # The endpoint stays thin: it delegates create; blob-vs-native routing lives in the facade.
    seen: dict[str, object] = {}

    def _stub(  # noqa: ANN001
        ns,
        so,
        segments,
        data,
        *,
        mode=None,
        properties=None,
        allow_external_blobs=False,
        external_blob_bases=None,
    ) -> CreateTableResponse:
        seen["segments"] = segments
        seen["mode"] = mode
        seen["allow_external_blobs"] = allow_external_blobs  # proves the endpoint forwards the setting
        seen["external_blob_bases"] = external_blob_bases  # the allowlist is forwarded too
        return CreateTableResponse(location="s3://x/t", version=1)

    monkeypatch.setattr("catalog.services.dataplane.create_table", _stub)
    resp = client.post(
        "/v1/table/media$clips/create?mode=overwrite",
        content=_arrow_ipc(pa.table({"id": [1]})),
        headers=ARROW_STREAM,
    )

    assert resp.status_code == 200
    assert seen == {
        "segments": ["media", "clips"],
        "mode": "overwrite",
        "allow_external_blobs": False,
        "external_blob_bases": [],
    }


def test_merge_insert_maps_spec_09_query_params(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.merge_insert_into_table.return_value = MergeInsertIntoTableResponse(version=2)
    client.post(
        "/v1/table/db$t/merge_insert?on=id&when_matched_update_all=true"
        "&when_matched_update_all_filt=score>0.5&timeout=30s&use_index=true&branch=exp",
        content=b"A",
        headers=ARROW_STREAM,
    )
    req = fake_ns.merge_insert_into_table.call_args.args[0]
    assert req.when_matched_update_all_filt == "score>0.5"
    assert req.timeout == "30s"
    assert req.use_index is True
    assert req.branch == "exp"


def test_list_table_versions_maps_descending_and_branch(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.list_table_versions.return_value = ListTableVersionsResponse(versions=[])
    client.post("/v1/table/db$t/version/list?descending=true&branch=exp")
    req = fake_ns.list_table_versions.call_args.args[0]
    assert req.descending is True
    assert req.branch == "exp"


# --- response shaping / content types (our logic) -------------------------- #


def test_exists_returns_200(client: TestClient, fake_ns: MagicMock) -> None:
    # Spec 0.9: existence is conveyed as 200 (was 204 in earlier revisions).
    fake_ns.table_exists.return_value = None
    assert client.post("/v1/table/db$t/exists").status_code == 200


def test_count_rows_returns_plain_integer(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.count_table_rows.return_value = 7
    resp = client.post("/v1/table/db$t/count_rows", json={})
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "7"


def test_query_returns_arrow_file_bytes(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.query_table.return_value = b"ARROWFILEBYTES"
    resp = client.post("/v1/table/db$t/query", json={"k": 5, "vector": {}})
    assert resp.headers["content-type"].startswith("application/vnd.apache.arrow.file")
    assert resp.content == b"ARROWFILEBYTES"


# --- error → HTTP / Problem-Details mapping (our logic) --------------------- #


def test_domain_not_found_maps_to_404_problem_json(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.describe_table.side_effect = TableNotFoundError("table 'x' not found")
    resp = client.post("/v1/table/db$t/describe")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404 and body["code"] == 4


def test_domain_conflict_maps_to_409(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.declare_table.side_effect = TableAlreadyExistsError("exists")
    assert client.post("/v1/table/db$t/declare", json={}).status_code == 409


def test_backend_stub_message_maps_to_501(client: TestClient, fake_ns: MagicMock) -> None:
    # native.call laundering: a backend that stubs an op with "not implemented" surfaces as 501 (spec
    # "unsupported"), not a 500. rename_table is now implemented in-process (#5b), so register_table — a
    # still-native-delegated op — stands in for a genuinely-unwired backend op.
    fake_ns.register_table.side_effect = RuntimeError("register_table not implemented")
    resp = client.post("/v1/table/db$t/register", json={"location": "s3://b/db$t"})
    assert resp.status_code == 501
    assert resp.json()["status"] == 501


def test_list_branches_routes_to_dataset_branches(client: TestClient, monkeypatch) -> None:
    # Branches are now backed in-process via pylance `ds.branches` (was a native 501).
    dataset = MagicMock()
    dataset.branches.list.return_value = {
        "exp": {"parent_branch": None, "parent_version": 2, "create_at": 1, "manifest_size": 9}
    }
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post("/v1/table/db1$users/branches/list")
    assert resp.status_code == 200
    assert resp.json()["branches"]["exp"]["parentVersion"] == 2  # serialized with the spec's camelCase alias


def test_create_branch_maps_from_version_to_int_reference(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post("/v1/table/db$t/branches/create", json={"name": "exp", "from_version": 3})
    assert resp.status_code == 200
    dataset.create_branch.assert_called_once_with("exp", 3)  # fromVersion → int reference


def test_create_branch_maps_from_branch_and_version_to_tuple(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post(
        "/v1/table/db$t/branches/create", json={"name": "x", "from_branch": "exp", "from_version": 2}
    )
    assert resp.status_code == 200
    dataset.create_branch.assert_called_once_with("x", ("exp", 2))  # (branch, version) reference


def test_create_branch_from_main_uses_no_reference(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post("/v1/table/db$t/branches/create", json={"name": "exp"})
    assert resp.status_code == 200
    dataset.create_branch.assert_called_once_with("exp", None)  # neither → latest of main


def test_delete_branch_routes_to_dataset(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post("/v1/table/db$t/branches/delete", json={"name": "exp"})
    assert resp.status_code == 200
    dataset.branches.delete.assert_called_once_with("exp")


def test_insert_stamps_the_real_version_on_lineage(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # Insert's native response carries only a transaction_id; the shared trailer reopens the dataset for
    # the version it produced and stamps it on the WROTE edge — it used to emit version=None.
    from lance_namespace import InsertIntoTableResponse

    fake_ns.insert_into_table.return_value = InsertIntoTableResponse(transaction_id="tx1")
    dataset = MagicMock()
    dataset.version = 7
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    captured = _capture_measured_emit(monkeypatch)

    resp = client.post("/v1/table/db$t/insert", content=b"ARROWSTREAM", headers=ARROW_STREAM)
    assert resp.status_code == 200
    assert captured["version"] == 7  # the real Lance version, not None


# --- #110 lineage-emit coverage: schema-evolution / index / restore / register / declare now emit, ---
# --- through the shared best-effort + version-pinned read-back trailer (lineage_deps).            ---


def _capture_emit(monkeypatch, module: str) -> dict[str, object]:
    """Patch the endpoint module's emit_write_event to record its kwargs (versionless-marker ops)."""
    captured: dict[str, object] = {}

    async def _cap(_emitter: object, _segments: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(f"catalog.api.v1.endpoints.{module}.emit_write_event", _cap)
    return captured


def _capture_measured_emit(monkeypatch) -> dict[str, object]:
    """Patch the shared trailer's emit_write_event to record what a measured op finally emits."""
    captured: dict[str, object] = {}

    async def _cap(_emitter: object, _segments: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("catalog.api.lineage_deps.emit_write_event", _cap)
    return captured


def test_add_columns_emits_pinned_schema_evolution_lineage(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # A schema change must carry the NEW per-version schema so /schema + /columns follow the evolution —
    # and the read-back must be PINNED to the response's version, so a concurrent writer between the
    # commit and the read can't attach a later version's schema to this WROTE edge.
    from lance_namespace import AlterTableAddColumnsResponse

    monkeypatch.setattr(
        "catalog.services.dataplane.add_columns", lambda *a, **k: AlterTableAddColumnsResponse(version=4)
    )
    seen: dict[str, object] = {}

    def _readback(_ns: object, _so: object, _segments: object, pin_version: object = None) -> object:
        seen["pin"] = pin_version
        return pin_version, [{"name": "x", "type": "int64"}]

    monkeypatch.setattr("catalog.services.dataplane.read_version_and_schema", _readback)
    captured = _capture_measured_emit(monkeypatch)

    resp = client.post("/v1/table/db$t/add_columns", json={"new_columns": [{"name": "x", "expression": "1"}]})
    assert resp.status_code == 200
    assert seen["pin"] == 4  # the read-back opened the dataset AT the version the response reported
    assert captured["operation"] == "add_columns"
    assert captured["version"] == 4
    assert captured["schema_fields"] == [{"name": "x", "type": "int64"}]  # post-evolution schema rides along


def test_create_index_emits_lineage_at_readback_version(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # The native index response carries only a transaction_id → the new manifest version is read back.
    from lance_namespace import CreateTableIndexResponse

    fake_ns.create_table_index.return_value = CreateTableIndexResponse(transaction_id="tx")
    dataset = MagicMock()
    dataset.version = 9
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    captured = _capture_measured_emit(monkeypatch)

    resp = client.post("/v1/table/db$t/create_index", json={"column": "vec", "index_type": "IVF_PQ"})
    assert resp.status_code == 200
    assert captured["operation"] == "create_index"
    assert captured["version"] == 9  # read back off the dataset, not None


def test_create_index_succeeds_when_readback_fails(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # The index op is COMMITTED before the lineage read-back runs — a transient reopen failure must
    # degrade the emit to versionless, never turn the committed op into an error response.
    from lance_namespace import CreateTableIndexResponse

    fake_ns.create_table_index.return_value = CreateTableIndexResponse(transaction_id="tx")

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("transient object-store hiccup")

    monkeypatch.setattr("catalog.services.dataplane.open_dataset", _boom)
    captured = _capture_measured_emit(monkeypatch)

    resp = client.post("/v1/table/db$t/create_index", json={"column": "vec", "index_type": "IVF_PQ"})
    assert resp.status_code == 200  # the committed index build still returns success
    assert captured["operation"] == "create_index"
    assert captured["version"] is None  # degraded to a versionless marker; reconcile recovers the version
    assert captured["schema_fields"] == []


def test_restore_emits_lineage_at_new_version(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    from lance_namespace import RestoreTableResponse

    fake_ns.restore_table.return_value = RestoreTableResponse(transaction_id="tx")
    dataset = MagicMock()
    dataset.version = 12
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    captured = _capture_measured_emit(monkeypatch)

    resp = client.post("/v1/table/db$t/restore", json={"version": 3})
    assert resp.status_code == 200
    assert captured["operation"] == "restore_table"
    assert captured["version"] == 12  # the NEW current version after restore


def test_create_exist_ok_reads_schema_back_instead_of_trusting_payload(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # ExistOk may have KEPT an existing table (nothing written, response.version = the existing version):
    # the payload's schema may then belong to a table that was never created — the true schema must be
    # read back PINNED at that version, never parsed from the payload.
    from lance_namespace import CreateTableResponse

    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=5)
    seen: dict[str, object] = {}

    def _readback(_ns: object, _so: object, _segments: object, pin_version: object = None) -> object:
        seen["pin"] = pin_version
        return pin_version, [{"name": "true_col", "type": "int64"}]

    def _payload_bomb(*_a: object, **_k: object) -> object:
        raise AssertionError("ExistOk create must not trust the request payload's schema")

    monkeypatch.setattr("catalog.services.dataplane.read_version_and_schema", _readback)
    monkeypatch.setattr("catalog.services.dataplane.payload_schema_fields", _payload_bomb)

    resp = client.post("/v1/table/db$t/create?mode=exist_ok", content=b"ARROWSTREAM", headers=ARROW_STREAM)
    assert resp.status_code == 200
    assert seen["pin"] == 5  # schema read back pinned at the EXISTING table's version


def test_create_parses_payload_schema_without_dataset_reopen(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # A plain create writes exactly the request bytes — the schema facet comes from the in-memory payload,
    # never from a describe + dataset reopen (which would add two network round trips per create).
    from lance_namespace import CreateTableResponse

    fake_ns.create_table.return_value = CreateTableResponse(location="s3://x", version=1)
    called: dict[str, object] = {}

    def _payload(_data: object, _segments: object) -> object:
        called["payload"] = True
        return [{"name": "p", "type": "int64"}]

    def _readback_bomb(*_a: object, **_k: object) -> object:
        raise AssertionError("plain create must not reopen the dataset for its schema")

    monkeypatch.setattr("catalog.services.dataplane.payload_schema_fields", _payload)
    monkeypatch.setattr("catalog.services.dataplane.read_version_and_schema", _readback_bomb)

    resp = client.post("/v1/table/db$t/create", content=b"ARROWSTREAM", headers=ARROW_STREAM)
    assert resp.status_code == 200
    assert called.get("payload") is True


def test_deregister_emits_marker_before_revoking_tuples(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # The DEREGISTER_TABLE marker must publish BEFORE revoke_ownership: on the http transport the caller's
    # bearer authorizes ingest against their write grant — revoke-first would 403 the marker (silently
    # dropped by the best-effort emitter) and the graph would keep showing the table as live.
    from lance_namespace import DeregisterTableResponse

    fake_ns.deregister_table.return_value = DeregisterTableResponse()
    order: list[str] = []

    async def _emit(*_a: object, **_k: object) -> None:
        order.append("emit")

    async def _revoke(*_a: object, **_k: object) -> None:
        order.append("revoke")

    monkeypatch.setattr("catalog.api.v1.endpoints.tables.emit_write_event", _emit)
    monkeypatch.setattr("catalog.api.fga_deps.revoke_ownership", _revoke)

    resp = client.post("/v1/table/db$t/deregister")
    assert resp.status_code == 200
    assert order == ["emit", "revoke"]  # marker first, while the caller's grant still authorizes ingest


def test_register_emits_versionless_marker_with_source_uri(
    client: TestClient, fake_ns: MagicMock, monkeypatch
) -> None:
    # Register attaches an existing (possibly external) location: versionless + source_uri, and it keys a
    # CREATED edge (register_table ∈ lineage _CREATE_OPS); reconcile back-fills the real on-disk version.
    from lance_namespace import RegisterTableResponse

    fake_ns.register_table.return_value = RegisterTableResponse(location="s3://bucket/t")
    captured = _capture_emit(monkeypatch, "tables")

    resp = client.post("/v1/table/db$t/register", json={"location": "s3://bucket/t"})
    assert resp.status_code == 200
    assert captured["operation"] == "register_table"
    assert captured["version"] is None  # versionless — no reopen of a possibly-external location on the path
    assert captured["source_uri"] == "s3://bucket/t"


def test_declare_emits_versionless_marker(client: TestClient, fake_ns: MagicMock, monkeypatch) -> None:
    from lance_namespace import DeclareTableResponse

    fake_ns.declare_table.return_value = DeclareTableResponse(location="s3://bucket/t")
    captured = _capture_emit(monkeypatch, "tables")

    resp = client.post("/v1/table/db$t/declare", json={})
    assert resp.status_code == 200
    assert captured["operation"] == "declare_table"
    assert captured["version"] is None  # reserved, no data yet
    assert captured["source_uri"] == "s3://bucket/t"


# --- version ops: the native bindings are `request: dict`-typed; native.call must marshal the pydantic ---
# --- request to a dict, else a TypeError surfaces as a fake 501. These guard that fix (audit finding). ---


def test_describe_version_marshals_request_to_a_dict(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.describe_table_version.return_value = DescribeTableVersionResponse(
        version=TableVersion(version=2, manifest_path="_versions/2.manifest")
    )
    resp = client.post("/v1/table/db$t/version/describe?version=2")
    assert resp.status_code == 200
    assert resp.json()["version"]["version"] == 2
    arg = fake_ns.describe_table_version.call_args.args[0]
    assert isinstance(arg, dict) and arg["id"] == ["db", "t"] and arg["version"] == 2  # a dict, not the model


def test_describe_version_missing_maps_to_404(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.describe_table_version.side_effect = TableVersionNotFoundError("version 99 not found")
    resp = client.post("/v1/table/db$t/version/describe?version=99")
    assert resp.status_code == 404


def test_create_version_marshals_request_to_a_dict(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.create_table_version.return_value = CreateTableVersionResponse()
    resp = client.post(
        "/v1/table/db$t/version/create", json={"version": 2, "manifest_path": "_versions/2.manifest"}
    )
    assert resp.status_code == 200
    arg = fake_ns.create_table_version.call_args.args[0]
    assert isinstance(arg, dict) and arg["id"] == ["db", "t"] and arg["version"] == 2


def test_batch_delete_versions_marshals_request_to_a_dict(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.batch_delete_table_versions.return_value = BatchDeleteTableVersionsResponse()
    resp = client.post(
        "/v1/table/db$t/version/delete", json={"ranges": [{"start_version": 1, "end_version": 1}]}
    )
    assert resp.status_code == 200
    arg = fake_ns.batch_delete_table_versions.call_args.args[0]
    assert isinstance(arg, dict) and arg["id"] == ["db", "t"]


def test_request_validation_maps_to_422_problem_json(client: TestClient) -> None:
    # UpdateTableRequest requires `updates`; an empty body fails validation.
    resp = client.post("/v1/table/db$t/update", json={})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Validation Error"


# --- data-plane request building (our logic; fake dataset) ----------------- #


def test_update_builds_updates_dict_and_reads_real_count_key(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    # pylance's update() returns the UpdateResult dict with key `num_rows_updated` (NOT `num_updated_rows`,
    # and NOT an attribute) — the response must read that exact key, else updated_rows is always 0.
    dataset.update.return_value = {"num_rows_updated": 2}
    dataset.version = 5
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post("/v1/table/db$t/update", json={"predicate": "id = 1", "updates": [["name", "'x'"]]})
    assert resp.status_code == 200
    assert dataset.update.call_args.args[0] == {"name": "'x'"}  # list-of-pairs -> dict
    assert dataset.update.call_args.kwargs["where"] == "id = 1"
    assert resp.json() == {"updated_rows": 2, "version": 5}


def test_add_columns_builds_transforms(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    dataset.version = 3
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post(
        "/v1/table/db$t/add_columns",
        json={"new_columns": [{"name": "score", "expression": "cast(id as double)"}]},
    )
    assert resp.status_code == 200
    assert dataset.add_columns.call_args.args[0] == {"score": "cast(id as double)"}


def test_create_tag_routes_to_dataset_tags(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post("/v1/table/db$t/tags/create", json={"tag": "v1", "version": 1})
    assert resp.status_code == 200
    dataset.tags.create.assert_called_once_with("v1", 1)  # no branch → bare int (current/main branch)


def test_create_tag_with_branch_passes_branch_version_tuple(client: TestClient, monkeypatch) -> None:
    # A branch-scoped tag must pass (branch, version) — a bare int would resolve against main, tagging the
    # WRONG version. (Was silently dropping `branch`.)
    dataset = MagicMock()
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post("/v1/table/db$t/tags/create", json={"tag": "rc", "version": 5, "branch": "dev"})
    assert resp.status_code == 200
    dataset.tags.create.assert_called_once_with("rc", ("dev", 5))


def test_alter_columns_converts_json_arrow_type_to_pyarrow(client: TestClient, monkeypatch) -> None:
    # A re-type carries `data_type` as a JsonArrowDataType dict; it must reach pylance as a real pa.DataType,
    # not the JSON dict (which would 500 at the Rust boundary). float32→float16 is the documented vector case.
    import pyarrow as pa

    dataset = MagicMock()
    dataset.version = 4
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: dataset)
    resp = client.post(
        "/v1/table/db$t/alter_columns",
        json={"alterations": [{"path": "embedding", "data_type": {"type": "float16"}}]},
    )
    assert resp.status_code == 200
    alteration = dataset.alter_columns.call_args.args[0]  # alterations are passed positionally (*alterations)
    assert alteration["data_type"] == pa.float16()


def test_alter_columns_unsupported_type_is_400_not_500(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: MagicMock())
    resp = client.post(
        "/v1/table/db$t/alter_columns",
        json={"alterations": [{"path": "c", "data_type": {"type": "some_exotic_type"}}]},
    )
    assert resp.status_code == 400  # clear InvalidInput, not a silent Rust-boundary 500


def test_update_with_empty_updates_is_400(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("catalog.services.dataplane.open_dataset", lambda *a, **k: MagicMock())
    resp = client.post("/v1/table/db$t/update", json={"updates": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 13  # InvalidInput
