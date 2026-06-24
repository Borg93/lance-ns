"""Table data endpoints: Arrow-IPC writes, query, count, update/delete, plans."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from lance_namespace import (
    AnalyzeTableQueryPlanRequest,
    CountTableRowsRequest,
    CreateTableRequest,
    CreateTableResponse,
    DeleteFromTableRequest,
    DeleteFromTableResponse,
    ExplainTableQueryPlanRequest,
    InsertIntoTableRequest,
    InsertIntoTableResponse,
    InvalidInputError,
    MergeInsertIntoTableRequest,
    MergeInsertIntoTableResponse,
    QueryTableRequest,
    UpdateTableRequest,
    UpdateTableResponse,
)

from app.api import fga_deps
from app.api.dependencies import (
    FgaClientDep,
    LineageEmitterDep,
    NamespaceDep,
    SettingsDep,
    StorageOptionsDep,
)
from app.api.security import CurrentToken
from app.core import fga
from app.core.identifiers import parse_identifier
from app.core.serialization import dump
from app.services import dataplane, native

ARROW_STREAM = "application/vnd.apache.arrow.stream"
ARROW_FILE = "application/vnd.apache.arrow.file"

router = APIRouter(prefix="/v1/table", tags=["data"])


@router.post("/{id}/create", response_model_exclude_none=True)
async def create_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    background_tasks: BackgroundTasks,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    mode: str | None = None,
    properties_header: Annotated[str | None, Header(alias="x-lance-table-properties")] = None,
) -> CreateTableResponse:
    properties = None
    if properties_header:
        try:
            properties = json.loads(properties_header)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"x-lance-table-properties is not valid JSON: {exc}") from exc
    segments = parse_identifier(id, settings.delimiter)
    req = CreateTableRequest(id=segments, mode=mode, properties=properties)
    response: CreateTableResponse = await run_in_threadpool(native.call, ns, "create_table", req, data)
    # Make the caller owner + link the new table to its parent so it inherits the cascade.
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    # Record provenance authoritatively: the catalog knows the verified principal. Fire-and-forget
    # (after the response, best-effort) so the lineage service can never block/fail a create. The
    # canonical id keeps the lineage Dataset == the OpenFGA object id == the catalog table id.
    background_tasks.add_task(
        emitter.emit_create,
        table_id=fga.canonical_object_id(segments, delimiter=settings.delimiter),
        namespace=fga.parent_namespace_id(segments, delimiter=settings.delimiter) or "",
        author=token.sub if token is not None else None,
        version=1,
    )
    return response


@router.post("/{id}/insert", response_model_exclude_none=True)
def insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    mode: str | None = None,
) -> InsertIntoTableResponse:
    req = InsertIntoTableRequest(id=parse_identifier(id, settings.delimiter), mode=mode)
    return native.call(ns, "insert_into_table", req, data)


@router.post("/{id}/merge_insert", response_model_exclude_none=True)
def merge_insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    on: str | None = None,
    when_matched_update_all: bool | None = None,
    when_not_matched_insert_all: bool | None = None,
    when_not_matched_by_source_delete: bool | None = None,
) -> MergeInsertIntoTableResponse:
    req = MergeInsertIntoTableRequest(
        id=parse_identifier(id, settings.delimiter),
        on=on,
        when_matched_update_all=when_matched_update_all,
        when_not_matched_insert_all=when_not_matched_insert_all,
        when_not_matched_by_source_delete=when_not_matched_by_source_delete,
    )
    return native.call(ns, "merge_insert_into_table", req, data)


@router.post("/{id}/update", response_model_exclude_none=True)
def update_table(
    id: str, body: UpdateTableRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> UpdateTableResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.update_table(ns, so, body)


@router.post("/{id}/delete", response_model_exclude_none=True)
def delete_from_table(
    id: str, body: DeleteFromTableRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> DeleteFromTableResponse:
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.delete_from_table(ns, so, body)


@router.post("/{id}/query")
def query_table(id: str, body: QueryTableRequest, ns: NamespaceDep, settings: SettingsDep) -> Response:
    body.id = parse_identifier(id, settings.delimiter)
    data = native.call(ns, "query_table", body)
    return Response(content=data, media_type=ARROW_FILE)


@router.post("/{id}/count_rows")
def count_table_rows(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: CountTableRowsRequest | None = None
) -> Response:
    req = body or CountTableRowsRequest()
    req.id = parse_identifier(id, settings.delimiter)
    count = native.call(ns, "count_table_rows", req)
    return PlainTextResponse(str(count))


@router.post("/{id}/explain_plan")
def explain_table_query_plan(
    id: str, body: ExplainTableQueryPlanRequest, ns: NamespaceDep, settings: SettingsDep
) -> Response:
    body.id = parse_identifier(id, settings.delimiter)
    result = native.call(ns, "explain_table_query_plan", body)
    return PlainTextResponse(result if isinstance(result, str) else json.dumps(dump(result)))


@router.post("/{id}/analyze_plan")
def analyze_table_query_plan(
    id: str, body: AnalyzeTableQueryPlanRequest, ns: NamespaceDep, settings: SettingsDep
) -> Response:
    body.id = parse_identifier(id, settings.delimiter)
    result = native.call(ns, "analyze_table_query_plan", body)
    return PlainTextResponse(result if isinstance(result, str) else json.dumps(dump(result)))
