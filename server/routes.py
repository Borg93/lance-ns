"""All Lance Namespace REST Catalog routes (spec.yaml surface).

Each route maps a spec path to a method on the native namespace backend. Where
the installed backend doesn't implement a method (version skew), the call raises
``UnsupportedOperationError`` -> HTTP 501, which is spec-correct.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from server.common import (
    ARROW_FILE,
    build_request,
    call,
    dump,
    get_delimiter,
    get_ns,
    json_op,
    parse_id,
)

router = APIRouter()


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _id(request: Request, id: str) -> list[str]:
    return parse_id(id, get_delimiter(request))


# --------------------------------------------------------------------------- #
# Namespace metadata
# --------------------------------------------------------------------------- #


@router.post("/v1/namespace/{id}/create")
async def create_namespace(id: str, request: Request):
    return await json_op(
        request,
        "CreateNamespaceRequest",
        "create_namespace",
        _id(request, id),
        body=await _body(request),
    )


@router.get("/v1/namespace/{id}/list")
async def list_namespaces(
    id: str,
    request: Request,
    page_token: Optional[str] = None,
    limit: Optional[int] = None,
):
    return await json_op(
        request,
        "ListNamespacesRequest",
        "list_namespaces",
        _id(request, id),
        page_token=page_token,
        limit=limit,
    )


@router.post("/v1/namespace/{id}/describe")
async def describe_namespace(id: str, request: Request):
    return await json_op(
        request,
        "DescribeNamespaceRequest",
        "describe_namespace",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/namespace/{id}/drop")
async def drop_namespace(id: str, request: Request):
    return await json_op(
        request,
        "DropNamespaceRequest",
        "drop_namespace",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/namespace/{id}/exists")
async def namespace_exists(id: str, request: Request):
    await call(
        get_ns(request),
        "namespace_exists",
        build_request("NamespaceExistsRequest", _id(request, id)),
    )
    return Response(status_code=204)


@router.get("/v1/namespace/{id}/table/list")
async def list_tables(
    id: str,
    request: Request,
    page_token: Optional[str] = None,
    limit: Optional[int] = None,
):
    return await json_op(
        request,
        "ListTablesRequest",
        "list_tables",
        _id(request, id),
        page_token=page_token,
        limit=limit,
    )


# --------------------------------------------------------------------------- #
# Table metadata
# --------------------------------------------------------------------------- #


@router.get("/v1/table")
async def list_all_tables(
    request: Request, page_token: Optional[str] = None, limit: Optional[int] = None
):
    return await json_op(
        request,
        "ListTablesRequest",
        "list_all_tables",
        [],
        page_token=page_token,
        limit=limit,
    )


@router.post("/v1/table/version/batch-create")
async def batch_create_versions(request: Request):
    return await json_op(
        request,
        "BatchCreateTableVersionsRequest",
        "batch_create_table_versions",
        None,
        body=await _body(request),
    )


@router.post("/v1/table/batch-commit")
async def batch_commit(request: Request):
    return await json_op(
        request,
        "BatchCommitTablesRequest",
        "batch_commit_tables",
        None,
        body=await _body(request),
    )


@router.post("/v1/table/{id}/declare")
async def declare_table(id: str, request: Request):
    return await json_op(
        request,
        "DeclareTableRequest",
        "declare_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/describe")
async def describe_table(
    id: str,
    request: Request,
    with_table_uri: Optional[bool] = None,
    load_detailed_metadata: Optional[bool] = None,
    check_declared: Optional[bool] = None,
):
    return await json_op(
        request,
        "DescribeTableRequest",
        "describe_table",
        _id(request, id),
        body=await _body(request),
        with_table_uri=with_table_uri,
        load_detailed_metadata=load_detailed_metadata,
        check_declared=check_declared,
    )


@router.post("/v1/table/{id}/exists")
async def table_exists(id: str, request: Request):
    await call(
        get_ns(request),
        "table_exists",
        build_request("TableExistsRequest", _id(request, id)),
    )
    return Response(status_code=204)


@router.post("/v1/table/{id}/drop")
async def drop_table(id: str, request: Request):
    return dump(
        await call(
            get_ns(request),
            "drop_table",
            build_request("DropTableRequest", _id(request, id)),
        )
    )


@router.post("/v1/table/{id}/deregister")
async def deregister_table(id: str, request: Request):
    return dump(
        await call(
            get_ns(request),
            "deregister_table",
            build_request("DeregisterTableRequest", _id(request, id)),
        )
    )


@router.post("/v1/table/{id}/register")
async def register_table(id: str, request: Request):
    return await json_op(
        request,
        "RegisterTableRequest",
        "register_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/rename")
async def rename_table(id: str, request: Request):
    return await json_op(
        request,
        "RenameTableRequest",
        "rename_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/restore")
async def restore_table(id: str, request: Request):
    return await json_op(
        request,
        "RestoreTableRequest",
        "restore_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/stats")
async def table_stats(id: str, request: Request):
    return await json_op(
        request,
        "GetTableStatsRequest",
        "get_table_stats",
        _id(request, id),
        body=await _body(request),
    )


# --------------------------------------------------------------------------- #
# Table data (Arrow IPC in; Arrow file / plain text out)
# --------------------------------------------------------------------------- #


@router.post("/v1/table/{id}/create")
async def create_table(id: str, request: Request, mode: Optional[str] = None):
    data = await request.body()
    body: dict = {}
    props = request.headers.get("x-lance-table-properties")
    if props:
        try:
            body["properties"] = json.loads(props)
        except json.JSONDecodeError:
            pass
    req = build_request(
        "CreateTableRequest",
        _id(request, id),
        body,
        mode=mode,
        location=request.headers.get("x-lance-table-location"),
    )
    return dump(await call(get_ns(request), "create_table", req, data))


@router.post("/v1/table/{id}/insert")
async def insert_into_table(id: str, request: Request, mode: Optional[str] = None):
    data = await request.body()
    req = build_request("InsertIntoTableRequest", _id(request, id), mode=mode)
    return dump(await call(get_ns(request), "insert_into_table", req, data))


@router.post("/v1/table/{id}/merge_insert")
async def merge_insert(
    id: str,
    request: Request,
    on: Optional[str] = None,
    when_matched_update_all: Optional[bool] = None,
    when_matched_update_all_filt: Optional[str] = None,
    when_not_matched_insert_all: Optional[bool] = None,
    when_not_matched_by_source_delete: Optional[bool] = None,
    when_not_matched_by_source_delete_filt: Optional[str] = None,
    timeout: Optional[str] = None,
    use_index: Optional[bool] = None,
):
    data = await request.body()
    req = build_request(
        "MergeInsertIntoTableRequest",
        _id(request, id),
        on=on,
        when_matched_update_all=when_matched_update_all,
        when_matched_update_all_filt=when_matched_update_all_filt,
        when_not_matched_insert_all=when_not_matched_insert_all,
        when_not_matched_by_source_delete=when_not_matched_by_source_delete,
        when_not_matched_by_source_delete_filt=when_not_matched_by_source_delete_filt,
        timeout=timeout,
        use_index=use_index,
    )
    return dump(await call(get_ns(request), "merge_insert_into_table", req, data))


@router.post("/v1/table/{id}/update")
async def update_table(id: str, request: Request):
    return await json_op(
        request,
        "UpdateTableRequest",
        "update_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/delete")
async def delete_from_table(id: str, request: Request):
    return await json_op(
        request,
        "DeleteFromTableRequest",
        "delete_from_table",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/query")
async def query_table(id: str, request: Request):
    body = await _body(request)
    body.setdefault(
        "vector", {}
    )  # vector is required by the model; allow filter-only scans
    req = build_request("QueryTableRequest", _id(request, id), body)
    data = await call(get_ns(request), "query_table", req)
    return Response(content=data, media_type=ARROW_FILE)


@router.post("/v1/table/{id}/count_rows")
async def count_rows(id: str, request: Request):
    n = await call(
        get_ns(request),
        "count_table_rows",
        build_request("CountTableRowsRequest", _id(request, id), await _body(request)),
    )
    return PlainTextResponse(str(n))


@router.post("/v1/table/{id}/explain_plan")
async def explain_plan(id: str, request: Request):
    res = await call(
        get_ns(request),
        "explain_table_query_plan",
        build_request(
            "ExplainTableQueryPlanRequest", _id(request, id), await _body(request)
        ),
    )
    return PlainTextResponse(res if isinstance(res, str) else json.dumps(dump(res)))


@router.post("/v1/table/{id}/analyze_plan")
async def analyze_plan(id: str, request: Request):
    res = await call(
        get_ns(request),
        "analyze_table_query_plan",
        build_request(
            "AnalyzeTableQueryPlanRequest", _id(request, id), await _body(request)
        ),
    )
    return PlainTextResponse(res if isinstance(res, str) else json.dumps(dump(res)))


# --------------------------------------------------------------------------- #
# Schema / column maintenance
# --------------------------------------------------------------------------- #


@router.post("/v1/table/{id}/add_columns")
async def add_columns(id: str, request: Request):
    return await json_op(
        request,
        "AlterTableAddColumnsRequest",
        "alter_table_add_columns",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/alter_columns")
async def alter_columns(id: str, request: Request):
    return await json_op(
        request,
        "AlterTableAlterColumnsRequest",
        "alter_table_alter_columns",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/drop_columns")
async def drop_columns(id: str, request: Request):
    return await json_op(
        request,
        "AlterTableDropColumnsRequest",
        "alter_table_drop_columns",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/backfill_column")
async def backfill_column(id: str, request: Request):
    return await json_op(
        request,
        "AlterTableBackfillColumnsRequest",
        "alter_table_backfill_columns",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/update_field_metadata")
async def update_field_metadata(id: str, request: Request):
    return await json_op(
        request,
        "UpdateFieldMetadataRequest",
        "update_field_metadata",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/schema_metadata/update")
async def update_schema_metadata(id: str, request: Request):
    body = await _body(request)
    meta = body["metadata"] if isinstance(body, dict) and "metadata" in body else body
    return await json_op(
        request,
        "UpdateTableSchemaMetadataRequest",
        "update_table_schema_metadata",
        _id(request, id),
        metadata=meta,
    )


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #


@router.post("/v1/table/{id}/create_index")
async def create_index(id: str, request: Request):
    return await json_op(
        request,
        "CreateTableIndexRequest",
        "create_table_index",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/create_scalar_index")
async def create_scalar_index(id: str, request: Request):
    return await json_op(
        request,
        "CreateTableIndexRequest",
        "create_table_scalar_index",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/index/list")
async def list_indices(
    id: str,
    request: Request,
    page_token: Optional[str] = None,
    limit: Optional[int] = None,
):
    return await json_op(
        request,
        "ListTableIndicesRequest",
        "list_table_indices",
        _id(request, id),
        page_token=page_token,
        limit=limit,
    )


@router.post("/v1/table/{id}/index/{index_name}/stats")
async def index_stats(id: str, index_name: str, request: Request):
    return await json_op(
        request,
        "DescribeTableIndexStatsRequest",
        "describe_table_index_stats",
        _id(request, id),
        body=await _body(request),
        index_name=index_name,
    )


@router.post("/v1/table/{id}/index/{index_name}/drop")
async def drop_index(id: str, index_name: str, request: Request):
    return await json_op(
        request,
        "DropTableIndexRequest",
        "drop_table_index",
        _id(request, id),
        index_name=index_name,
    )


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #


@router.post("/v1/table/{id}/tags/list")
async def list_tags(
    id: str,
    request: Request,
    page_token: Optional[str] = None,
    limit: Optional[int] = None,
):
    return await json_op(
        request,
        "ListTableTagsRequest",
        "list_table_tags",
        _id(request, id),
        page_token=page_token,
        limit=limit,
    )


@router.post("/v1/table/{id}/tags/create")
async def create_tag(id: str, request: Request):
    return await json_op(
        request,
        "CreateTableTagRequest",
        "create_table_tag",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/tags/delete")
async def delete_tag(id: str, request: Request):
    return await json_op(
        request,
        "DeleteTableTagRequest",
        "delete_table_tag",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/tags/update")
async def update_tag(id: str, request: Request):
    return await json_op(
        request,
        "UpdateTableTagRequest",
        "update_table_tag",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/tags/version")
async def tag_version(id: str, request: Request):
    return await json_op(
        request,
        "GetTableTagVersionRequest",
        "get_table_tag_version",
        _id(request, id),
        body=await _body(request),
    )


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #


@router.post("/v1/table/{id}/version/list")
async def list_versions(
    id: str,
    request: Request,
    page_token: Optional[str] = None,
    limit: Optional[int] = None,
):
    return await json_op(
        request,
        "ListTableVersionsRequest",
        "list_table_versions",
        _id(request, id),
        page_token=page_token,
        limit=limit,
    )


@router.post("/v1/table/{id}/version/create")
async def create_version(id: str, request: Request):
    return await json_op(
        request,
        "CreateTableVersionRequest",
        "create_table_version",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/version/describe")
async def describe_version(id: str, request: Request):
    return await json_op(
        request,
        "DescribeTableVersionRequest",
        "describe_table_version",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/table/{id}/version/delete")
async def delete_versions(id: str, request: Request):
    return await json_op(
        request,
        "BatchDeleteTableVersionsRequest",
        "batch_delete_table_versions",
        _id(request, id),
        body=await _body(request),
    )


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #


@router.post("/v1/transaction/{id}/describe")
async def describe_transaction(id: str, request: Request):
    return await json_op(
        request,
        "DescribeTransactionRequest",
        "describe_transaction",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/transaction/{id}/alter")
async def alter_transaction(id: str, request: Request):
    return await json_op(
        request,
        "AlterTransactionRequest",
        "alter_transaction",
        _id(request, id),
        body=await _body(request),
    )


# --------------------------------------------------------------------------- #
# Materialized views
# --------------------------------------------------------------------------- #


@router.post("/v1/materialized_view/{id}/create")
async def create_materialized_view(id: str, request: Request):
    return await json_op(
        request,
        "CreateMaterializedViewRequest",
        "create_materialized_view",
        _id(request, id),
        body=await _body(request),
    )


@router.post("/v1/materialized_view/{id}/refresh")
async def refresh_materialized_view(id: str, request: Request):
    return await json_op(
        request,
        "RefreshMaterializedViewRequest",
        "refresh_materialized_view",
        _id(request, id),
        body=await _body(request),
    )
