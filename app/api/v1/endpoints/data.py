"""Table data endpoints: Arrow-IPC writes, query, count, update/delete, plans."""

from __future__ import annotations

import json
import logging
import uuid
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
from app.api.security import CurrentToken, IDToken
from app.core import fga
from app.core.config import Settings
from app.core.identifiers import parse_identifier
from app.core.lineage_emit import DELETE, INSERT, MERGE_INSERT, UPDATE, LineageEmitter
from app.core.lineage_metadata import build_lineage_metadata, inject_into_arrow_stream
from app.core.serialization import dump
from app.services import dataplane, native

log = logging.getLogger(__name__)


def _queue_write_event(
    background_tasks: BackgroundTasks,
    emitter: LineageEmitter,
    settings: Settings,
    token: IDToken | None,
    segments: list[str],
    *,
    version: int | None,
    operation: str,
    authorization: str | None,
) -> None:
    """Queue a best-effort OpenLineage write event after the response (#19 — the same fire-and-forget
    path as create, for every catalog mutation). ``version=None`` (e.g. an insert whose response has
    no version) records the run + operation without asserting a Lance version on the ``WROTE`` edge."""
    background_tasks.add_task(
        emitter.emit_write,
        table_id=fga.canonical_object_id(segments, delimiter=settings.delimiter),
        namespace=fga.parent_namespace_id(segments, delimiter=settings.delimiter) or "",
        author=token.sub if token is not None else None,
        version=version,
        operation=operation,
        run_id=str(uuid.uuid4()),
        authorization=authorization,
    )


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
    authorization: Annotated[str | None, Header()] = None,
) -> CreateTableResponse:
    properties = None
    if properties_header:
        try:
            properties = json.loads(properties_header)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"x-lance-table-properties is not valid JSON: {exc}") from exc
    segments = parse_identifier(id, settings.delimiter)
    table_id = fga.canonical_object_id(segments, delimiter=settings.delimiter)
    namespace = fga.parent_namespace_id(segments, delimiter=settings.delimiter) or ""
    created_by = token.sub if token is not None else None
    run_id = str(uuid.uuid4())
    # #21: stamp the lineage coordinates into the Lance file's schema metadata so the data is
    # self-describing (reconcilable to the graph without the catalog). Best-effort — a payload we
    # can't re-encode must never fail the create over metadata; fall back to the original bytes.
    try:
        data = await run_in_threadpool(
            inject_into_arrow_stream,
            data,
            build_lineage_metadata(
                table_id=table_id, namespace=namespace, run_id=run_id, created_by=created_by
            ),
        )
    except Exception as exc:  # noqa: BLE001 — lineage metadata is an enhancement, not a gate
        log.warning("lineage_metadata_inject_failed", extra={"table": table_id, "error": str(exc)})
    req = CreateTableRequest(id=segments, mode=mode, properties=properties)
    response: CreateTableResponse = await run_in_threadpool(native.call, ns, "create_table", req, data)
    # Make the caller owner + link the new table to its parent so it inherits the cascade.
    await fga_deps.seed_ownership(client, settings, token, resource="table", segments=segments)
    # Record provenance authoritatively: the catalog knows the verified principal. Fire-and-forget
    # (after the response, best-effort) so the lineage service can never block/fail a create. The
    # canonical id keeps the lineage Dataset == the OpenFGA object id == the catalog table id; the
    # caller's bearer is forwarded so ingest accepts it when the lineage service has OIDC on; the
    # ``run_id`` is the same one stamped into the Lance file above (#21).
    background_tasks.add_task(
        emitter.emit_create,
        table_id=table_id,
        namespace=namespace,
        author=created_by,
        version=response.version or 1,
        run_id=run_id,
        authorization=authorization,
    )
    return response


@router.post("/{id}/insert", response_model_exclude_none=True)
def insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    background_tasks: BackgroundTasks,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    mode: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> InsertIntoTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    req = InsertIntoTableRequest(id=segments, mode=mode)
    response: InsertIntoTableResponse = native.call(ns, "insert_into_table", req, data)
    # Insert's response carries no Lance version → record the run + operation without a version facet.
    _queue_write_event(
        background_tasks,
        emitter,
        settings,
        token,
        segments,
        version=None,
        operation=INSERT,
        authorization=authorization,
    )
    return response


@router.post("/{id}/merge_insert", response_model_exclude_none=True)
def merge_insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    background_tasks: BackgroundTasks,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    on: str | None = None,
    when_matched_update_all: bool | None = None,
    when_not_matched_insert_all: bool | None = None,
    when_not_matched_by_source_delete: bool | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> MergeInsertIntoTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    req = MergeInsertIntoTableRequest(
        id=segments,
        on=on,
        when_matched_update_all=when_matched_update_all,
        when_not_matched_insert_all=when_not_matched_insert_all,
        when_not_matched_by_source_delete=when_not_matched_by_source_delete,
    )
    response: MergeInsertIntoTableResponse = native.call(ns, "merge_insert_into_table", req, data)
    _queue_write_event(
        background_tasks,
        emitter,
        settings,
        token,
        segments,
        version=response.version,
        operation=MERGE_INSERT,
        authorization=authorization,
    )
    return response


@router.post("/{id}/update", response_model_exclude_none=True)
def update_table(
    id: str,
    body: UpdateTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
) -> UpdateTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: UpdateTableResponse = dataplane.update_table(ns, so, body)
    _queue_write_event(
        background_tasks,
        emitter,
        settings,
        token,
        segments,
        version=response.version,
        operation=UPDATE,
        authorization=authorization,
    )
    return response


@router.post("/{id}/delete", response_model_exclude_none=True)
def delete_from_table(
    id: str,
    body: DeleteFromTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
) -> DeleteFromTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: DeleteFromTableResponse = dataplane.delete_from_table(ns, so, body)
    _queue_write_event(
        background_tasks,
        emitter,
        settings,
        token,
        segments,
        version=response.version,
        operation=DELETE,
        authorization=authorization,
    )
    return response


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
