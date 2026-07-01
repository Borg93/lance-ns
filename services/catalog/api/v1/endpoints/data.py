"""Table data endpoints: Arrow-IPC writes, query, count, update/delete, plans."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from common import fga
from fastapi import APIRouter, Body, Header
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

from catalog.api import fga_deps
from catalog.api.dependencies import (
    FgaClientDep,
    LineageEmitterDep,
    NamespaceDep,
    SettingsDep,
    StorageOptionsDep,
)
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.core.lineage_emit import DELETE, INSERT, MERGE_INSERT, UPDATE, emit_write_event
from catalog.core.lineage_metadata import build_lineage_metadata, inject_into_arrow_stream
from catalog.core.serialization import dump
from catalog.services import dataplane, native

log = logging.getLogger(__name__)


ARROW_STREAM = "application/vnd.apache.arrow.stream"
ARROW_FILE = "application/vnd.apache.arrow.file"

# Cap on the create payload we'll decode→re-encode in-process to stamp lineage metadata (#21). Above
# this we skip the stamp (the graph still gets the create run); keeps a large create off a ~3x-memory
# re-encode on the request path. (#22 audit)
_MAX_INJECT_BYTES = 64 * 1024 * 1024

router = APIRouter(prefix="/v1/table", tags=["data"])


@router.post("/{id}/create", response_model_exclude_none=True)
async def create_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
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
    # Gated on lineage being enabled (the inject is a full Arrow decode→re-encode, ~3x the payload
    # in memory) and a size ceiling (don't re-encode an arbitrarily large body in-process); when off
    # or oversized we don't stamp a create_run_id the graph never receives. (#22 audit)
    if settings.lineage_emit_enabled and len(data) <= _MAX_INJECT_BYTES:
        try:
            data = await run_in_threadpool(
                inject_into_arrow_stream,
                data,
                build_lineage_metadata(table_id=table_id, namespace=namespace, run_id=run_id),
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
    # Inline-await (NOT BackgroundTasks — no retry, dies with the worker; fastapi anti-pattern) so the event
    # reaches the durable Dapr/JetStream transport before the response. emit_create is best-effort internally,
    # so it never fails the create; JetStream + the consumer's idempotent MERGE-on-run_id give durability.
    await emitter.emit_create(
        table_id=table_id,
        namespace=namespace,
        author=created_by,
        version=response.version or 1,
        run_id=run_id,
        authorization=authorization,
        source_uri=response.location,  # the real Lance URI → #23 reconcile can read the on-disk file
    )
    return response


@router.post("/{id}/insert", response_model_exclude_none=True)
async def insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    mode: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> InsertIntoTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    req = InsertIntoTableRequest(id=segments, mode=mode)
    response: InsertIntoTableResponse = await run_in_threadpool(
        native.call, ns, "insert_into_table", req, data
    )
    # Insert's response carries only a transaction_id, not the Lance version it produced — reopen the
    # dataset to read it (like update/delete) so the WROTE edge records the real version, not null.
    version = await run_in_threadpool(dataplane.current_version, ns, so, segments)
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=version,
        operation=INSERT,
        authorization=authorization,
    )
    return response


@router.post("/{id}/merge_insert", response_model_exclude_none=True)
async def merge_insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
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
    response: MergeInsertIntoTableResponse = await run_in_threadpool(
        native.call, ns, "merge_insert_into_table", req, data
    )
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=response.version,
        operation=MERGE_INSERT,
        authorization=authorization,
    )
    return response


@router.post("/{id}/update", response_model_exclude_none=True)
async def update_table(
    id: str,
    body: UpdateTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> UpdateTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: UpdateTableResponse = await run_in_threadpool(dataplane.update_table, ns, so, body)
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=response.version,
        operation=UPDATE,
        authorization=authorization,
    )
    return response


@router.post("/{id}/delete", response_model_exclude_none=True)
async def delete_from_table(
    id: str,
    body: DeleteFromTableRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> DeleteFromTableResponse:
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: DeleteFromTableResponse = await run_in_threadpool(dataplane.delete_from_table, ns, so, body)
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
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
