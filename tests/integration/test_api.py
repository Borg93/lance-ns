"""Integration tests for *our* REST layer.

The namespace backend is faked, so every assertion is about code we wrote:
identifier parsing from the path, routing to the correct operation, request
assembly (query params / headers / body), response serialization and
content-types, and error → HTTP / Problem-Details mapping. No lance operations
are exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from lance_namespace import (
    CreateNamespaceResponse,
    CreateTableResponse,
    DescribeTableResponse,
    ListNamespacesResponse,
    TableAlreadyExistsError,
    TableNotFoundError,
    UnsupportedOperationError,
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


# --- response shaping / content types (our logic) -------------------------- #


def test_exists_returns_204(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.table_exists.return_value = None
    assert client.post("/v1/table/db$t/exists").status_code == 204


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
    fake_ns.rename_table.side_effect = RuntimeError("rename_table not implemented")
    resp = client.post("/v1/table/db$t/rename", json={"new_table_name": "t2"})
    assert resp.status_code == 501
    assert resp.json()["status"] == 501


def test_branch_route_parses_id_and_maps_unsupported(client: TestClient, fake_ns: MagicMock) -> None:
    fake_ns.list_table_branches.side_effect = UnsupportedOperationError("Not supported: list_table_branches")
    resp = client.post("/v1/table/db1$users/branches/list")
    assert resp.status_code == 501
    assert fake_ns.list_table_branches.call_args.args[0].id == ["db1", "users"]


def test_request_validation_maps_to_422_problem_json(client: TestClient) -> None:
    # UpdateTableRequest requires `updates`; an empty body fails validation.
    resp = client.post("/v1/table/db$t/update", json={})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Validation Error"


# --- data-plane request building (our logic; fake dataset) ----------------- #


def test_update_builds_updates_dict(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    dataset.update.return_value = MagicMock(num_updated_rows=2)
    dataset.version = 5
    monkeypatch.setattr("app.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post("/v1/table/db$t/update", json={"predicate": "id = 1", "updates": [["name", "'x'"]]})
    assert resp.status_code == 200
    assert dataset.update.call_args.args[0] == {"name": "'x'"}  # list-of-pairs -> dict
    assert dataset.update.call_args.kwargs["where"] == "id = 1"
    assert resp.json() == {"updated_rows": 2, "version": 5}


def test_add_columns_builds_transforms(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    dataset.version = 3
    monkeypatch.setattr("app.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post(
        "/v1/table/db$t/add_columns",
        json={"new_columns": [{"name": "score", "expression": "cast(id as double)"}]},
    )
    assert resp.status_code == 200
    assert dataset.add_columns.call_args.args[0] == {"score": "cast(id as double)"}


def test_create_tag_routes_to_dataset_tags(client: TestClient, monkeypatch) -> None:
    dataset = MagicMock()
    monkeypatch.setattr("app.services.dataplane.open_dataset", lambda *a, **k: dataset)

    resp = client.post("/v1/table/db$t/tags/create", json={"tag": "v1", "version": 1})
    assert resp.status_code == 200
    dataset.tags.create.assert_called_once_with("v1", 1)


def test_update_with_empty_updates_is_400(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.services.dataplane.open_dataset", lambda *a, **k: MagicMock())
    resp = client.post("/v1/table/db$t/update", json={"updates": []})
    assert resp.status_code == 400
    assert resp.json()["code"] == 13  # InvalidInput
