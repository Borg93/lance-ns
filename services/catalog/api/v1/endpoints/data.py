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
    CreateTableResponse,
    DeleteFromTableRequest,
    DeleteFromTableResponse,
    DescribeTableRequest,
    ExplainTableQueryPlanRequest,
    InsertIntoTableRequest,
    InsertIntoTableResponse,
    InvalidInputError,
    LanceNamespace,
    MergeInsertIntoTableRequest,
    MergeInsertIntoTableResponse,
    QueryTableRequest,
    TableNotFoundError,
    UpdateTableRequest,
    UpdateTableResponse,
)

from catalog.api import fga_deps, lineage_deps
from catalog.api.dependencies import (
    FgaClientDep,
    LineageEmitterDep,
    NamespaceDep,
    SettingsDep,
    StorageOptionsDep,
)
from catalog.api.security import CurrentToken
from catalog.core.identifiers import parse_identifier
from catalog.core.lineage_emit import DELETE, INSERT, MERGE_INSERT, UPDATE
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


def _table_exists(ns: LanceNamespace, segments: list[str]) -> bool:
    """True if a table already lives at ``segments`` (declared-only counts — it already holds an owner
    grant). Used to decide whether a create ``mode=Overwrite`` is destroying an EXISTING table (which then
    needs an owner-tier gate) vs creating a fresh one. Blocking native call → run in a threadpool."""
    try:
        native.call(ns, "describe_table", DescribeTableRequest(id=segments, check_declared=True))
        return True
    except TableNotFoundError:
        return False


@router.post("/{id}/create", response_model_exclude_none=True)
async def create_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    so: StorageOptionsDep,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    mode: str | None = None,
    properties: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> CreateTableResponse:
    """Create a Lance table from an Arrow-IPC stream — ``create_table``; seeds ownership + lineage.

    ``properties`` is the spec-0.9 JSON-encoded query parameter. Client-supplied ``storage_options``
    are deliberately NOT accepted: storage access is the catalog's to vend (two-tier secret model),
    so callers can't redirect writes or splice credentials.
    """
    parsed_properties = None
    if properties:
        try:
            parsed_properties = json.loads(properties)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"table properties is not valid JSON: {exc}") from exc
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
    # mode=Overwrite is spec-defined as "the existing table is DROPPED and a new table created" (lance
    # namespace.md). ``authorize`` only gated this create at writer-tier can_create_table on the PARENT — but
    # a DROP needs owner-tier can_drop. So if an Overwrite is about to DESTROY an existing table, require
    # owner-tier on it FIRST (before the irreversible write) — else a mere namespace writer could overwrite
    # and, via the ownership reset below, seize another user's table. Fresh-id Overwrite creates nothing to
    # gate. FGA-off skips it (no ACL to protect).
    # Short-circuits: the describe (_table_exists) only runs on an Overwrite with FGA on.
    overwrote_existing = (
        (mode or "").lower() == "overwrite"
        and settings.fga_enabled
        and client is not None
        and await run_in_threadpool(_table_exists, ns, segments)
    )
    if overwrote_existing:
        await fga_deps.require_can_drop_table(client, settings, token, segments=segments)
    # ``dataplane.create_table`` picks the write path by schema off the event loop: a blob-v2 column needs
    # file format 2.2 (native create pins 2.1 and rejects it) → a direct 2.2 write; else → native create. (§9)
    response: CreateTableResponse = await run_in_threadpool(
        dataplane.create_table,
        ns,
        so,
        segments,
        data,
        mode=mode,
        properties=parsed_properties,
        allow_external_blobs=settings.allow_external_blobs,
        external_blob_bases=settings.external_blob_base_list,
    )
    # An Overwrite that replaced an EXISTING table (owner-authorized above) resets its ACL: revoke the prior
    # incarnation's grants (any reader/writer/validator that must not survive onto the reused id) before
    # re-seeding the overwriter. Only when we actually overwrote — a fresh create has nothing to revoke, and
    # revoking on a non-owner path is what the audit flagged as an eviction vector (now gated out).
    if overwrote_existing:
        await fga_deps.revoke_ownership(client, settings, resource="table", segments=segments)
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
    # The per-version column schema (blob/vector-aware) for the WROTE edge (#24). A create/Overwrite writes
    # exactly the request bytes, so the payload schema IS the table's schema — parsed in memory, no
    # describe + dataset reopen round trip. ExistOk is the exception: it may have KEPT an existing table
    # (nothing written, response.version = the existing version), so the payload schema could belong to a
    # table that was never created — read the true schema back PINNED at that version instead. Best-effort
    # either way (failure → []).
    if (mode or "").lower() in ("existok", "exist_ok"):
        _, schema_fields = await run_in_threadpool(
            dataplane.read_version_and_schema, ns, so, segments, response.version
        )
    else:
        schema_fields = await run_in_threadpool(dataplane.payload_schema_fields, data, segments)
    await emitter.emit_create(
        table_id=table_id,
        namespace=namespace,
        author=created_by,
        version=response.version or 1,
        run_id=run_id,
        authorization=authorization,
        source_uri=response.location,  # the real Lance URI → #23 reconcile can read the on-disk file
        schema_fields=schema_fields,
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
    branch: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> InsertIntoTableResponse:
    """Append Arrow-IPC rows — ``insert_into_table``; emits an INSERT lineage event.
    ``branch`` targets a non-main branch (spec 0.9 query param for Arrow-IPC-body ops)."""
    segments = parse_identifier(id, settings.delimiter)
    req = InsertIntoTableRequest(id=segments, mode=mode, branch=branch)
    response: InsertIntoTableResponse = await run_in_threadpool(
        native.call, ns, "insert_into_table", req, data
    )
    # Insert's response carries only a transaction_id, not the Lance version it produced — the shared
    # trailer reads version + schema off ONE reopen (best-effort) so the WROTE edge records the real version.
    await lineage_deps.emit_measured_write(
        emitter,
        segments,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        operation=INSERT,
        authorization=authorization,
    )
    return response


@router.post("/{id}/merge_insert", response_model_exclude_none=True)
async def merge_insert_into_table(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    emitter: LineageEmitterDep,
    data: Annotated[bytes, Body(media_type=ARROW_STREAM)],
    on: str | None = None,
    when_matched_update_all: bool | None = None,
    when_matched_update_all_filt: str | None = None,
    when_not_matched_insert_all: bool | None = None,
    when_not_matched_by_source_delete: bool | None = None,
    when_not_matched_by_source_delete_filt: str | None = None,
    timeout: str | None = None,
    use_index: bool | None = None,
    branch: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> MergeInsertIntoTableResponse:
    """Upsert Arrow-IPC rows — ``merge_insert_into_table``; emits a MERGE_INSERT lineage event.
    The ``*_filt`` SQL filters, ``timeout``, ``use_index`` and ``branch`` are spec-0.9 query params."""
    segments = parse_identifier(id, settings.delimiter)
    req = MergeInsertIntoTableRequest(
        id=segments,
        on=on,
        when_matched_update_all=when_matched_update_all,
        when_matched_update_all_filt=when_matched_update_all_filt,
        when_not_matched_insert_all=when_not_matched_insert_all,
        when_not_matched_by_source_delete=when_not_matched_by_source_delete,
        when_not_matched_by_source_delete_filt=when_not_matched_by_source_delete_filt,
        timeout=timeout,
        use_index=use_index,
        branch=branch,
    )
    response: MergeInsertIntoTableResponse = await run_in_threadpool(
        native.call, ns, "merge_insert_into_table", req, data
    )
    # merge can add/change columns (schema drift at this version) → record the post-write schema, read
    # PINNED at the version this merge produced so a concurrent writer can't smuggle in a later schema.
    await lineage_deps.emit_measured_write(
        emitter,
        segments,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        operation=MERGE_INSERT,
        authorization=authorization,
        pin_version=response.version,
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
    """Update rows matching a predicate — ``update_table``; emits an UPDATE lineage event."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: UpdateTableResponse = await run_in_threadpool(dataplane.update_table, ns, so, body)
    await lineage_deps.emit_measured_write(
        emitter,
        segments,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        operation=UPDATE,
        authorization=authorization,
        pin_version=response.version,
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
    """Delete rows matching a predicate — ``delete_from_table``; emits a DELETE lineage event."""
    segments = parse_identifier(id, settings.delimiter)
    body.id = segments
    response: DeleteFromTableResponse = await run_in_threadpool(dataplane.delete_from_table, ns, so, body)
    # A row-delete doesn't change columns, but the WROTE edge at this new version still records the
    # (unchanged) schema so dataset_schema(version=N) is populated for every version, not just writes.
    await lineage_deps.emit_measured_write(
        emitter,
        segments,
        ns=ns,
        so=so,
        settings=settings,
        token=token,
        operation=DELETE,
        authorization=authorization,
        pin_version=response.version,
    )
    return response


@router.post("/{id}/query")
def query_table(id: str, body: QueryTableRequest, ns: NamespaceDep, settings: SettingsDep) -> Response:
    """Run a query and return matching rows as an Arrow-IPC file — wraps ``query_table``."""
    body.id = parse_identifier(id, settings.delimiter)
    data = native.call(ns, "query_table", body)
    return Response(content=data, media_type=ARROW_FILE)


@router.post("/{id}/count_rows")
def count_table_rows(
    id: str, ns: NamespaceDep, settings: SettingsDep, body: CountTableRowsRequest | None = None
) -> Response:
    """Count the table's rows (optionally filtered) — ``count_table_rows``; returns plain text."""
    req = body or CountTableRowsRequest()
    req.id = parse_identifier(id, settings.delimiter)
    count = native.call(ns, "count_table_rows", req)
    return PlainTextResponse(str(count))


@router.post("/{id}/explain_plan")
def explain_table_query_plan(
    id: str, body: ExplainTableQueryPlanRequest, ns: NamespaceDep, settings: SettingsDep
) -> Response:
    """Return the logical query plan — ``explain_table_query_plan``; plain text."""
    body.id = parse_identifier(id, settings.delimiter)
    result = native.call(ns, "explain_table_query_plan", body)
    return PlainTextResponse(result if isinstance(result, str) else json.dumps(dump(result)))


@router.post("/{id}/analyze_plan")
def analyze_table_query_plan(
    id: str, body: AnalyzeTableQueryPlanRequest, ns: NamespaceDep, settings: SettingsDep
) -> Response:
    """Return the analyzed query plan with runtime metrics — ``analyze_table_query_plan``; plain text."""
    body.id = parse_identifier(id, settings.delimiter)
    result = native.call(ns, "analyze_table_query_plan", body)
    return PlainTextResponse(result if isinstance(result, str) else json.dumps(dump(result)))
