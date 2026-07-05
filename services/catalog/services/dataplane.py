"""Operations implemented in-process via pylance.

The native ``DirectoryNamespace`` stubs several table data, schema, and tag
operations. These functions fill the gap: resolve the table's dataset via the
namespace, then perform the operation with pylance.

Most functions take ``(ns, storage_options, request)`` and return the typed ``lance_namespace`` response
model. Exceptions: ``update_field_metadata`` takes ``(ns, storage_options, table_id, updates)``; and
``create_table`` is the one facade that receives the raw Arrow-IPC ``data`` and picks the write path by
schema — a blob-v2 column needs file format 2.2 (the native create pins 2.1 and rejects it), so it takes
a direct 2.2 write, while every other schema delegates to the native create.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

import lance
import pyarrow as pa
from common import blobs
from lance_namespace import (
    AlterTableAddColumnsRequest,
    AlterTableAddColumnsResponse,
    AlterTableAlterColumnsRequest,
    AlterTableAlterColumnsResponse,
    AlterTableDropColumnsRequest,
    AlterTableDropColumnsResponse,
    CreateTableBranchRequest,
    CreateTableBranchResponse,
    CreateTableRequest,
    CreateTableResponse,
    CreateTableTagRequest,
    CreateTableTagResponse,
    DeclareTableRequest,
    DeleteFromTableRequest,
    DeleteFromTableResponse,
    DeleteTableBranchRequest,
    DeleteTableBranchResponse,
    DeleteTableTagRequest,
    DeleteTableTagResponse,
    DescribeTableRequest,
    DropTableRequest,
    GetTableTagVersionRequest,
    GetTableTagVersionResponse,
    InvalidInputError,
    LanceNamespace,
    ListTableBranchesRequest,
    ListTableBranchesResponse,
    ListTableTagsRequest,
    ListTableTagsResponse,
    TableNotFoundError,
    TableTagNotFoundError,
    UnsupportedOperationError,
    UpdateFieldMetadataResponse,
    UpdateTableRequest,
    UpdateTableResponse,
    UpdateTableTagRequest,
    UpdateTableTagResponse,
)

from catalog.core.namespace import open_dataset
from catalog.services import native

StorageOptions = dict[str, str]


def _table_id(req: object) -> list[str]:
    """Return the request's table identifier, or raise if it is empty."""
    table_id = getattr(req, "id", None)
    if not table_id:
        raise InvalidInputError("table identifier is required")
    return table_id


def _version(ns: LanceNamespace, so: StorageOptions, table_id: list[str]) -> int:
    """Return the table's current dataset version after an in-place mutation."""
    return open_dataset(ns, so, table_id).version


def current_version(ns: LanceNamespace, so: StorageOptions, table_id: list[str]) -> int:
    """The table's current Lance version — for stamping lineage after a native op whose response omits it
    (``insert`` returns only a ``transaction_id``, so we reopen the dataset like update/delete)."""
    return _version(ns, so, table_id)


def create_table(
    ns: LanceNamespace,
    so: StorageOptions,
    segments: list[str],
    data: bytes,
    *,
    mode: str | None = None,
    properties: dict[str, str] | None = None,
    allow_external_blobs: bool = False,
) -> CreateTableResponse:
    """Create a table from an Arrow-IPC payload, choosing the write path by schema.

    A blob-v2 column requires file format 2.2, which the native create pins at 2.1 and rejects — such a
    schema takes the direct 2.2 write; every other schema delegates to the native create. Runs off the
    event loop (blocking pyarrow decode + Lance/S3 IO), so the endpoint stays a single delegated call.
    ``allow_external_blobs`` permits ``Blob.from_uri`` columns pointing outside the dataset root.
    """
    if _schema_is_blob(data):
        return _create_blob_table(
            ns, so, segments, data, mode=mode, properties=properties, allow_external=allow_external_blobs
        )
    request = CreateTableRequest(id=segments, mode=mode, properties=properties)
    response: CreateTableResponse = native.call(ns, "create_table", request, data)
    # #88: the native create echoes the catalog's ROOT storage creds back in ``storage_options`` — strip
    # them so a create caller never receives root credentials. Storage access is vended ONLY through the
    # dedicated ``/credentials`` endpoint (scoped, two-tier secret model), never as a side effect of create.
    response.storage_options = None
    return response


def _schema_is_blob(data: bytes) -> bool:
    """True when the Arrow-IPC ``data``'s schema carries a blob-v2 column.

    An unparseable body returns ``False`` so it falls through to the native create, which surfaces the
    real decode error — a genuine bug in detection is NOT swallowed (only the Arrow parse failure is).
    """
    try:
        return blobs.schema_has_blob(pa.ipc.open_stream(data).schema)
    except (pa.ArrowInvalid, OSError):
        return False


def _write_blob(
    table: pa.Table, uri: str, so: StorageOptions, *, mode: str, allow_external: bool
) -> lance.LanceDataset:
    """Write a blob-v2 table at file format 2.2. ``allow_external`` opts into ``Blob.from_uri`` columns
    that point outside the dataset root (lance_docs/guide.md — external blob bases)."""
    try:
        return lance.write_dataset(
            table,
            uri,
            mode=mode,
            storage_options=so,
            data_storage_version="2.2",
            allow_external_blob_outside_bases=allow_external,
        )
    except OSError as exc:
        # An external-pointer blob while the flag is off is a client error, not a 500 — surface a clear 400.
        # Match lance's specific phrase (NOT a bare "external"), so a genuine infra OSError on a path that
        # merely contains the word "external" still surfaces as a retryable 500 rather than a masked 400.
        if not allow_external and "outside registered external bases" in str(exc).lower():
            raise InvalidInputError(
                "blob column references an external object outside the dataset root; the catalog must be "
                "configured with allow_external_blobs to accept external-pointer (Blob.from_uri) columns"
            ) from exc
        raise


def _create_blob_table(
    ns: LanceNamespace,
    so: StorageOptions,
    segments: list[str],
    data: bytes,
    *,
    mode: str | None,
    properties: dict[str, str] | None,
    allow_external: bool,
) -> CreateTableResponse:
    """Create a blob-v2 table at file format 2.2 (the native create pins 2.1 and rejects it).

    Honours the create ``mode`` against a *written* table (``ExistOk`` keeps it, ``Overwrite`` replaces its
    data, ``Create`` conflicts). A *declared-only* table — one that exists in the namespace but was never
    written (a bare ``POST /declare``, or a declare→write that crashed before the write) — has no readable
    dataset, so every mode simply lands the first data version into its already-declared location; this keeps
    the multi-step create idempotent and crash-safe, and never opens a table that isn't there (which 500'd).
    A brand-new table is ``declare``-d to learn its canonical location, then written at
    ``data_storage_version="2.2"`` (lance_docs/guide.md — Version Compatibility). Any failed fresh write is
    rolled back with ``drop_table`` so the name stays retryable rather than stuck describable-but-unreadable.
    """
    table = pa.ipc.open_stream(data).read_all()
    normalized = (mode or "create").lower()
    existing, only_declared = _existing_location(ns, segments)

    if existing is not None and not only_declared:  # a written, readable table already lives here
        if normalized == "overwrite":
            dataset = _write_blob(table, existing, so, mode="overwrite", allow_external=allow_external)
            return CreateTableResponse(location=existing, version=dataset.version, properties=properties)
        if normalized in ("existok", "exist_ok"):  # keep it untouched, just report its current version
            version = lance.dataset(existing, storage_options=so).version
            return CreateTableResponse(location=existing, version=version, properties=properties)
        # `create` against a written table → let declare surface the canonical TableAlreadyExists conflict.

    if existing is not None and only_declared:  # declared, no data yet → write into it (all modes)
        return _write_blob_into(ns, table, existing, so, segments, properties, allow_external=allow_external)

    location = ns.declare_table(DeclareTableRequest(id=segments, properties=properties)).location
    if not location:
        raise InvalidInputError("namespace did not return a location for the declared table")
    return _write_blob_into(ns, table, location, so, segments, properties, allow_external=allow_external)


def _write_blob_into(
    ns: LanceNamespace,
    table: pa.Table,
    location: str,
    so: StorageOptions,
    segments: list[str],
    properties: dict[str, str] | None,
    *,
    allow_external: bool,
) -> CreateTableResponse:
    """Write the blob table's first data version into an already-declared ``location``, rolling the declare
    back with ``drop_table`` on failure so the name stays retryable rather than stuck declared-but-unreadable.
    """
    try:
        dataset = _write_blob(table, location, so, mode="create", allow_external=allow_external)
    except Exception:
        with suppress(Exception):  # best-effort rollback; re-raise the real write error
            ns.drop_table(DropTableRequest(id=segments))
        raise
    return CreateTableResponse(location=location, version=dataset.version, properties=properties)


def _existing_location(ns: LanceNamespace, segments: list[str]) -> tuple[str | None, bool]:
    """``(location, is_only_declared)`` for the table, or ``(None, False)`` if it does not exist.

    ``check_declared=True`` makes the namespace surface a declared-but-unwritten table (rather than raising
    TableNotFound), and ``is_only_declared`` distinguishes it from a written one — a declared-only table has
    no readable dataset, so the caller must NOT try to open it (that would 500).
    """
    try:
        resp = ns.describe_table(DescribeTableRequest(id=segments, with_table_uri=True, check_declared=True))
    except TableNotFoundError:
        return None, False
    location = getattr(resp, "table_uri", None) or getattr(resp, "location", None)
    return location, bool(getattr(resp, "is_only_declared", False))


# Scalar Arrow type names → pyarrow factory, for the alter_columns re-type path. A ``JsonArrowDataType``
# carries a ``type`` name (+ optional ``fields``/``length`` for complex types); pylance's ``alter_columns``
# needs a real ``pa.DataType``, so we convert. Covers the documented re-types (e.g. float32→float16 on an
# embedding column); an unsupported/complex type raises a clear 400 instead of a silent Rust-boundary 500.
_SCALAR_ARROW: dict[str, Callable[[], pa.DataType]] = {
    "null": pa.null,
    "bool": pa.bool_,
    "boolean": pa.bool_,
    "int8": pa.int8,
    "int16": pa.int16,
    "int32": pa.int32,
    "int64": pa.int64,
    "uint8": pa.uint8,
    "uint16": pa.uint16,
    "uint32": pa.uint32,
    "uint64": pa.uint64,
    "float16": pa.float16,
    "halffloat": pa.float16,
    "float32": pa.float32,
    "float": pa.float32,
    "float64": pa.float64,
    "double": pa.float64,
    "string": pa.string,
    "utf8": pa.string,
    "large_string": pa.large_string,
    "binary": pa.binary,
    "large_binary": pa.large_binary,
    "date32": pa.date32,
    "date64": pa.date64,
}


def _json_arrow_to_pa_type(dt: dict[str, Any]) -> pa.DataType:
    """Convert a ``JsonArrowDataType`` dict (``{type, fields?, length?}``) to a ``pyarrow.DataType``.

    Handles scalars + fixed-size-list (vector embeddings). An unsupported/complex type raises
    ``InvalidInputError`` (400) rather than letting a dict reach pylance and fail as a 500 at the boundary.
    """
    name = str(dt.get("type") or "").lower()
    factory = _SCALAR_ARROW.get(name)
    if factory is not None:
        return factory()
    if name in ("fixed_size_list", "fixedsizelist"):
        fields, length = dt.get("fields") or [], dt.get("length")
        if fields and length:
            return pa.list_(_json_arrow_to_pa_type(fields[0].get("type") or {}), int(length))
    raise InvalidInputError(f"unsupported alter_columns data_type: {dt.get('type')!r}")


def update_table(ns: LanceNamespace, so: StorageOptions, req: UpdateTableRequest) -> UpdateTableResponse:
    """Apply SQL ``[path, expression]`` updates to matching rows."""
    table_id = _table_id(req)
    updates = dict(req.updates or [])
    if not updates:
        raise InvalidInputError("update requires at least one [path, expression] pair")
    result = open_dataset(ns, so, table_id).update(updates, where=req.predicate)
    # pylance's update() returns an UpdateResult TypedDict (a plain dict at runtime); the row count is
    # `num_rows_updated`. (The previous `getattr(result, "num_updated_rows", ...)` was wrong twice — attr
    # access on a dict + wrong key — so updated_rows was hard-wired to 0 on every successful update.)
    updated = result.get("num_rows_updated") if isinstance(result, dict) else None
    return UpdateTableResponse(
        updated_rows=updated if updated is not None else 0, version=_version(ns, so, table_id)
    )


def delete_from_table(
    ns: LanceNamespace, so: StorageOptions, req: DeleteFromTableRequest
) -> DeleteFromTableResponse:
    """Delete rows matching the request predicate."""
    table_id = _table_id(req)
    open_dataset(ns, so, table_id).delete(req.predicate)
    return DeleteFromTableResponse(version=_version(ns, so, table_id))


def add_columns(
    ns: LanceNamespace, so: StorageOptions, req: AlterTableAddColumnsRequest
) -> AlterTableAddColumnsResponse:
    """Add columns computed from per-column SQL expressions."""
    table_id = _table_id(req)
    columns = req.new_columns or []
    # The spec also allows a `virtual_column` (UDF/Docker-backed) instead of a SQL `expression`. That needs
    # a UDF execution backend we don't run, so reject it as a spec-correct 501 — not a 400 (it's a valid
    # request for an unsupported feature, not invalid input).
    if any(getattr(c, "virtual_column", None) is not None and not c.expression for c in columns):
        raise UnsupportedOperationError("virtual_column add_columns is not supported by this backend")
    transforms = {c.name: c.expression for c in columns if c.expression}
    if not transforms:
        raise InvalidInputError("add_columns requires a name and SQL expression per column")
    open_dataset(ns, so, table_id).add_columns(transforms)
    return AlterTableAddColumnsResponse(version=_version(ns, so, table_id))


def alter_columns(
    ns: LanceNamespace, so: StorageOptions, req: AlterTableAlterColumnsRequest
) -> AlterTableAlterColumnsResponse:
    """Rename / re-type / change nullability of existing columns."""
    table_id = _table_id(req)
    alterations: list[dict[str, object]] = []
    for entry in req.alterations or []:
        alteration: dict[str, object] = {"path": entry.path}
        if entry.rename is not None:
            alteration["name"] = entry.rename
        if entry.nullable is not None:
            alteration["nullable"] = entry.nullable
        dt = getattr(entry, "data_type", None)
        if dt is not None:
            # data_type is a JsonArrowDataType dict; pylance needs a real pa.DataType, not the JSON dict.
            alteration["data_type"] = _json_arrow_to_pa_type(dt if isinstance(dt, dict) else dt.model_dump())
        alterations.append(alteration)
    # pylance accepts plain dict alterations at runtime; its stub types them as
    # AlterColumn (a TypedDict), which ty can't match from dict[str, object].
    open_dataset(ns, so, table_id).alter_columns(*alterations)  # ty: ignore[invalid-argument-type]
    return AlterTableAlterColumnsResponse(version=_version(ns, so, table_id))


def drop_columns(
    ns: LanceNamespace, so: StorageOptions, req: AlterTableDropColumnsRequest
) -> AlterTableDropColumnsResponse:
    """Drop the named columns from the table."""
    table_id = _table_id(req)
    open_dataset(ns, so, table_id).drop_columns(list(req.columns or []))
    return AlterTableDropColumnsResponse(version=_version(ns, so, table_id))


def update_field_metadata(
    ns: LanceNamespace, so: StorageOptions, table_id: list[str], updates: list[dict[str, Any]]
) -> UpdateFieldMetadataResponse:
    """Merge/replace per-field metadata for the given field paths."""
    field_updates = {u["path"]: dict(u.get("metadata") or {}) for u in updates if u.get("path")}
    replace = any(bool(u.get("replace")) for u in updates)
    open_dataset(ns, so, table_id).update_field_metadata(field_updates, replace=replace)
    # A None value is the key-deletion signal for the backend; drop those from the
    # echoed map since the response model's field values are non-nullable strings.
    fields = {path: {k: v for k, v in meta.items() if v is not None} for path, meta in field_updates.items()}
    return UpdateFieldMetadataResponse(version=_version(ns, so, table_id), fields=fields)


def list_tags(ns: LanceNamespace, so: StorageOptions, req: ListTableTagsRequest) -> ListTableTagsResponse:
    """List the table's tags as ``{name: TagContents{version, manifest_size, branch}}``."""
    table_id = _table_id(req)
    tags: dict[str, dict[str, Any]] = {}
    for name, tag in open_dataset(ns, so, table_id).tags.list().items():
        # pylance's Tag is a TypedDict (plain dict at runtime), so read by key.
        entry = tag if isinstance(tag, dict) else {"version": getattr(tag, "version", None)}
        tags[name] = {
            "version": entry.get("version"),
            "manifest_size": entry.get("manifest_size") or 0,
            "branch": entry.get("branch"),  # None for a tag on main (TagContents.branch is optional)
        }
    # model_validate coerces the inner dicts into TagContents (not exported to name directly).
    return ListTableTagsResponse.model_validate({"tags": tags})


def _tag_reference(branch: str | None, version: int | None) -> int | tuple[str | None, int | None] | None:
    """Map the spec's optional ``branch`` + ``version`` to a pylance tag ``reference``: a bare int resolves
    against the CURRENT branch (main), so a branch-scoped tag must pass the ``(branch, version)`` tuple."""
    return (branch, version) if branch is not None else version


def create_tag(ns: LanceNamespace, so: StorageOptions, req: CreateTableTagRequest) -> CreateTableTagResponse:
    """Tag the given table version with a name (honoring the request's optional ``branch``)."""
    open_dataset(ns, so, _table_id(req)).tags.create(req.tag, _tag_reference(req.branch, req.version))
    return CreateTableTagResponse()


def get_tag_version(
    ns: LanceNamespace, so: StorageOptions, req: GetTableTagVersionRequest
) -> GetTableTagVersionResponse:
    """Return the table version a tag points to."""
    tags = open_dataset(ns, so, _table_id(req)).tags
    version = tags.get_version(req.tag)
    if version is None:
        raise TableTagNotFoundError(f"tag {req.tag!r} not found")
    # Echo the branch the tag lives on (None for main) so a non-main tag isn't reported as main.
    entry = tags.list().get(req.tag) or {}
    return GetTableTagVersionResponse(version=version, branch=entry.get("branch"))


def update_tag(ns: LanceNamespace, so: StorageOptions, req: UpdateTableTagRequest) -> UpdateTableTagResponse:
    """Move an existing tag to a new table version (honoring the request's optional ``branch``)."""
    open_dataset(ns, so, _table_id(req)).tags.update(req.tag, _tag_reference(req.branch, req.version))
    return UpdateTableTagResponse()


def delete_tag(ns: LanceNamespace, so: StorageOptions, req: DeleteTableTagRequest) -> DeleteTableTagResponse:
    """Delete a tag from the table."""
    open_dataset(ns, so, _table_id(req)).tags.delete(req.tag)
    return DeleteTableTagResponse()


def _branch_reference(req: CreateTableBranchRequest) -> int | tuple[str | None, int | None] | None:
    """Map the spec's ``from_branch`` / ``from_version`` to pylance ``create_branch``'s ``reference``.

    fromBranch + fromVersion → ``(branch, version)``; fromBranch only → ``(branch, None)`` (latest of that
    branch); fromVersion only → the ``version`` int (on main); neither → ``None`` (latest of main).
    """
    if req.from_branch is not None:
        return (req.from_branch, req.from_version)
    if req.from_version is not None:
        return req.from_version
    return None


def list_branches(
    ns: LanceNamespace, so: StorageOptions, req: ListTableBranchesRequest
) -> ListTableBranchesResponse:
    """List the table's branches as ``{name: BranchContents}``, read from pylance ``ds.branches``.

    The native ``DirectoryNamespace`` 501s branch ops, but ``lance.LanceDataset`` implements them, so we
    back them in-process here exactly like tags. A ``Branch`` is a TypedDict (plain dict at runtime).
    """
    branches: dict[str, dict[str, Any]] = {}
    for name, branch in open_dataset(ns, so, _table_id(req)).branches.list().items():
        entry = branch if isinstance(branch, dict) else {}
        branches[name] = {
            "parent_branch": entry.get("parent_branch"),
            "parent_version": entry.get("parent_version"),
            "create_at": entry.get("create_at"),
            "manifest_size": entry.get("manifest_size") or 0,
            "metadata": entry.get("metadata") or {},
        }
    return ListTableBranchesResponse.model_validate({"branches": branches})


def create_branch(
    ns: LanceNamespace, so: StorageOptions, req: CreateTableBranchRequest
) -> CreateTableBranchResponse:
    """Create a branch from main (or a source branch/version) — maps to pylance ``create_branch``."""
    open_dataset(ns, so, _table_id(req)).create_branch(req.name, _branch_reference(req))
    return CreateTableBranchResponse()


def delete_branch(
    ns: LanceNamespace, so: StorageOptions, req: DeleteTableBranchRequest
) -> DeleteTableBranchResponse:
    """Delete a branch from the table."""
    open_dataset(ns, so, _table_id(req)).branches.delete(req.name)
    return DeleteTableBranchResponse()
