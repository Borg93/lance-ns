"""Coverage verifier for the Lance Namespace REST Catalog.

Exercises every spec.yaml operation against a running server (default
http://localhost:2333) and prints a per-operation coverage matrix:

  OK    -> 2xx/204 (implemented and working)
  UNSUP -> 501 (not implemented by the pinned lance-namespace backend; spec-correct)
  FAIL  -> unexpected 4xx/5xx (needs attention)

A curated "core lifecycle" subset is asserted to be OK; the rest is reported.
Run:  uv run --with requests --with pyarrow --no-project python smoke_test.py
"""

from __future__ import annotations

import sys

import pyarrow as pa
import requests

BASE = "http://localhost:2333"
ARROW = {"Content-Type": "application/vnd.apache.arrow.stream"}
NS, T = "db1", "db1$users"

results: list[tuple[str, str, int, str]] = []


def ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as w:
        w.write_table(table)
    return sink.getvalue().to_pybytes()


def do(
    op: str, method: str, path: str, *, json=None, data=None, headers=None
) -> requests.Response:
    url = f"{BASE}{path}"
    try:
        r = requests.request(
            method, url, json=json, data=data, headers=headers, timeout=60
        )
        snippet = (
            ""
            if r.headers.get("content-type", "").startswith("application/vnd.apache")
            else r.text[:80]
        )
        results.append((op, f"{method} {path.split('?')[0]}", r.status_code, snippet))
        return r
    except Exception as e:  # noqa: BLE001
        results.append((op, f"{method} {path.split('?')[0]}", -1, repr(e)[:80]))
        raise


def main() -> None:
    tbl = pa.table(
        {"id": pa.array([1, 2, 3], pa.int64()), "name": ["ana", "bob", "cleo"]}
    )
    more = pa.table({"id": pa.array([4, 5], pa.int64()), "name": ["dan", "eve"]})

    # clean slate
    requests.post(f"{BASE}/v1/table/{T}/drop")
    requests.post(f"{BASE}/v1/namespace/{NS}/drop")

    do("(health)", "GET", "/livez")
    do("(ready)", "GET", "/readyz")

    # ---- namespace ----
    do(
        "CreateNamespace",
        "POST",
        f"/v1/namespace/{NS}/create",
        json={"properties": {"team": "ml"}},
    )
    do("NamespaceExists", "POST", f"/v1/namespace/{NS}/exists")
    do("ListNamespaces", "GET", "/v1/namespace/$/list")
    do("DescribeNamespace", "POST", f"/v1/namespace/{NS}/describe")

    # ---- table create / inspect ----
    do(
        "CreateTable",
        "POST",
        f"/v1/table/{T}/create?mode=overwrite",
        data=ipc(tbl),
        headers=ARROW,
    )
    do("DeclareTable", "POST", f"/v1/table/{NS}$decl/declare", json={})
    do("ListTables", "GET", f"/v1/namespace/{NS}/table/list")
    do("ListAllTables", "GET", "/v1/table")
    do(
        "DescribeTable",
        "POST",
        f"/v1/table/{T}/describe?with_table_uri=true&load_detailed_metadata=true&check_declared=true",
    )
    do("TableExists", "POST", f"/v1/table/{T}/exists")
    do("GetTableStats", "POST", f"/v1/table/{T}/stats", json={})

    # ---- data ----
    do(
        "InsertIntoTable",
        "POST",
        f"/v1/table/{T}/insert?mode=append",
        data=ipc(more),
        headers=ARROW,
    )
    do("CountTableRows", "POST", f"/v1/table/{T}/count_rows", json={})
    do(
        "QueryTable",
        "POST",
        f"/v1/table/{T}/query",
        json={"k": 10, "filter": "id >= 4"},
    )
    do(
        "ExplainTableQueryPlan",
        "POST",
        f"/v1/table/{T}/explain_plan",
        json={"query": {"k": 5, "filter": "id > 0"}},
    )
    do(
        "AnalyzeTableQueryPlan",
        "POST",
        f"/v1/table/{T}/analyze_plan",
        json={"query": {"k": 5, "filter": "id > 0"}},
    )
    do(
        "UpdateTable",
        "POST",
        f"/v1/table/{T}/update",
        json={"predicate": "id = 1", "updates": [["name", "'updated'"]]},
    )
    do("DeleteFromTable", "POST", f"/v1/table/{T}/delete", json={"predicate": "id = 5"})
    do(
        "MergeInsertIntoTable",
        "POST",
        f"/v1/table/{T}/merge_insert?on=id&when_matched_update_all=true&when_not_matched_insert_all=true",
        data=ipc(
            pa.table({"id": pa.array([2, 99], pa.int64()), "name": ["BOB", "zed"]})
        ),
        headers=ARROW,
    )

    # ---- schema / columns ----
    do(
        "AlterTableAddColumns",
        "POST",
        f"/v1/table/{T}/add_columns",
        json={"new_columns": [{"name": "score", "expression": "id * 1.0"}]},
    )
    do(
        "AlterTableAlterColumns",
        "POST",
        f"/v1/table/{T}/alter_columns",
        json={"alterations": [{"path": "name", "nullable": True}]},
    )
    do(
        "UpdateTableSchemaMetadata",
        "POST",
        f"/v1/table/{T}/schema_metadata/update",
        json={"owner": "ml-team"},
    )
    do(
        "UpdateFieldMetadata",
        "POST",
        f"/v1/table/{T}/update_field_metadata",
        json={"updates": [{"path": "id", "metadata": {"pii": "false"}}]},
    )
    do(
        "AlterTableBackfillColumns",
        "POST",
        f"/v1/table/{T}/backfill_column",
        json={"column": "score"},
    )
    do(
        "AlterTableDropColumns",
        "POST",
        f"/v1/table/{T}/drop_columns",
        json={"columns": ["score"]},
    )

    # ---- indices ----
    do(
        "CreateTableScalarIndex",
        "POST",
        f"/v1/table/{T}/create_scalar_index",
        json={"column": "id", "index_type": "BTREE"},
    )
    do(
        "CreateTableIndex",
        "POST",
        f"/v1/table/{T}/create_index",
        json={"column": "id", "index_type": "BTREE"},
    )
    r = do("ListTableIndices", "POST", f"/v1/table/{T}/index/list")
    idx_name = None
    try:
        idxs = r.json().get("indexes") or r.json().get("indices") or []
        if idxs:
            idx_name = idxs[0].get("index_name") or idxs[0].get("name")
    except Exception:
        pass
    idx_name = idx_name or "id_idx"
    do(
        "DescribeTableIndexStats",
        "POST",
        f"/v1/table/{T}/index/{idx_name}/stats",
        json={},
    )
    do("DropTableIndex", "POST", f"/v1/table/{T}/index/{idx_name}/drop")

    # ---- tags ----
    do("ListTableTags", "POST", f"/v1/table/{T}/tags/list")
    do(
        "CreateTableTag",
        "POST",
        f"/v1/table/{T}/tags/create",
        json={"tag": "v1", "version": 1},
    )
    do("GetTableTagVersion", "POST", f"/v1/table/{T}/tags/version", json={"tag": "v1"})
    do(
        "UpdateTableTag",
        "POST",
        f"/v1/table/{T}/tags/update",
        json={"tag": "v1", "version": 2},
    )
    do("DeleteTableTag", "POST", f"/v1/table/{T}/tags/delete", json={"tag": "v1"})

    # ---- versions ----
    do("ListTableVersions", "POST", f"/v1/table/{T}/version/list")
    do(
        "DescribeTableVersion",
        "POST",
        f"/v1/table/{T}/version/describe",
        json={"version": 1},
    )
    do(
        "CreateTableVersion",
        "POST",
        f"/v1/table/{T}/version/create",
        json={"version": 999, "manifest_path": "x"},
    )
    do(
        "BatchDeleteTableVersions",
        "POST",
        f"/v1/table/{T}/version/delete",
        json={"ranges": [{"start_version": 0, "end_version": 1}]},
    )
    do(
        "BatchCreateTableVersions",
        "POST",
        "/v1/table/version/batch-create",
        json={"entries": []},
    )
    do("BatchCommitTables", "POST", "/v1/table/batch-commit", json={"operations": []})

    # ---- table lifecycle (register/rename/restore/deregister/drop) ----
    do(
        "RegisterTable",
        "POST",
        f"/v1/table/{NS}$reg/register",
        json={"location": f"s3://lance-catalog/{NS}/users.lance"},
    )
    do("RestoreTable", "POST", f"/v1/table/{T}/restore", json={"version": 1})
    do(
        "RenameTable",
        "POST",
        f"/v1/table/{NS}$decl/rename",
        json={"new_table_name": "decl2"},
    )
    do("DeregisterTable", "POST", f"/v1/table/{NS}$reg/deregister")

    # ---- transactions / materialized views (likely UNSUP in 0.7.7) ----
    do("DescribeTransaction", "POST", "/v1/transaction/txn1/describe")
    do("AlterTransaction", "POST", "/v1/transaction/txn1/alter", json={"actions": []})
    do(
        "CreateMaterializedView",
        "POST",
        f"/v1/materialized_view/{NS}$mv/create",
        json={"kind": "query", "source_query": "x", "output_schema": "x"},
    )
    do(
        "RefreshMaterializedView",
        "POST",
        f"/v1/materialized_view/{NS}$mv/refresh",
        json={},
    )

    # ---- cleanup ----
    do("DropTable", "POST", f"/v1/table/{T}/drop")
    do("DropNamespace", "POST", f"/v1/namespace/{NS}/drop")

    # ---- report ----
    def bucket(code: int) -> str:
        if code in (200, 201, 202, 204):
            return "OK"
        if code == 501:
            return "UNSUP"
        return "FAIL"

    print(f"\n{'OP':<28}{'ROUTE':<46}{'HTTP':<6}RESULT")
    print("-" * 100)
    for op, route, code, snip in results:
        print(f"{op:<28}{route:<46}{code!s:<6}{bucket(code)}  {snip}")

    ok = sum(1 for _, _, c, _ in results if bucket(c) == "OK")
    unsup = sum(1 for _, _, c, _ in results if bucket(c) == "UNSUP")
    fail = [(op, route, c, s) for op, route, c, s in results if bucket(c) == "FAIL"]
    print("-" * 100)
    print(f"OK={ok}  UNSUP(501)={unsup}  FAIL={len(fail)}  TOTAL={len(results)}")

    # Core lifecycle that MUST work end-to-end.
    must = {
        "CreateNamespace",
        "NamespaceExists",
        "ListNamespaces",
        "DescribeNamespace",
        "CreateTable",
        "ListTables",
        "ListAllTables",
        "DescribeTable",
        "TableExists",
        "InsertIntoTable",
        "CountTableRows",
        "QueryTable",
        "GetTableStats",
        "ListTableVersions",
        "DropTable",
        "DropNamespace",
    }
    by_op = {op: c for op, _, c, _ in results}
    broken = [op for op in must if bucket(by_op.get(op, 0)) != "OK"]
    if broken:
        print("\nCORE LIFECYCLE BROKEN:", broken)
        sys.exit(1)
    print("\nCORE LIFECYCLE: ALL OK ✅")


if __name__ == "__main__":
    try:
        main()
    except requests.ConnectionError:
        print("Could not connect to", BASE, file=sys.stderr)
        sys.exit(2)
