"""Operations implemented in-process via pylance.

The native ``DirectoryNamespace`` stubs several table data, schema, and tag
operations. These functions fill the gap: resolve the table's dataset via the
namespace, then perform the operation with pylance.

Each function takes ``(ns, storage_options, request)`` and returns the typed
``lance_namespace`` response model matching the spec response shape.
"""

from __future__ import annotations

from lance_namespace import (
    AlterTableAddColumnsRequest,
    AlterTableAddColumnsResponse,
    AlterTableAlterColumnsRequest,
    AlterTableAlterColumnsResponse,
    AlterTableDropColumnsRequest,
    AlterTableDropColumnsResponse,
    CreateTableTagRequest,
    CreateTableTagResponse,
    DeleteFromTableRequest,
    DeleteFromTableResponse,
    DeleteTableTagRequest,
    DeleteTableTagResponse,
    GetTableTagVersionRequest,
    GetTableTagVersionResponse,
    InvalidInputError,
    LanceNamespace,
    ListTableTagsRequest,
    ListTableTagsResponse,
    UpdateFieldMetadataResponse,
    UpdateTableRequest,
    UpdateTableResponse,
    UpdateTableTagRequest,
    UpdateTableTagResponse,
)

from app.core.namespace import open_dataset

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


def update_table(ns: LanceNamespace, so: StorageOptions, req: UpdateTableRequest) -> UpdateTableResponse:
    """Apply SQL ``[path, expression]`` updates to matching rows."""
    table_id = _table_id(req)
    updates = dict(req.updates or [])
    if not updates:
        raise InvalidInputError("update requires at least one [path, expression] pair")
    result = open_dataset(ns, so, table_id).update(updates, where=req.predicate)
    updated = getattr(result, "num_updated_rows", None)
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
    transforms = {c.name: c.expression for c in (req.new_columns or []) if c.expression}
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
        if getattr(entry, "data_type", None) is not None:
            alteration["data_type"] = entry.data_type
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
    ns: LanceNamespace, so: StorageOptions, table_id: list[str], updates: list[dict]
) -> UpdateFieldMetadataResponse:
    """Merge/replace per-field metadata for the given field paths."""
    field_updates = {u["path"]: dict(u.get("metadata") or {}) for u in updates if u.get("path")}
    replace = any(bool(u.get("replace")) for u in updates)
    open_dataset(ns, so, table_id).update_field_metadata(field_updates, replace=replace)
    return UpdateFieldMetadataResponse(version=_version(ns, so, table_id), fields=field_updates)


def list_tags(ns: LanceNamespace, so: StorageOptions, req: ListTableTagsRequest) -> ListTableTagsResponse:
    """List the table's tags as ``{name: {version, manifest_size}}``."""
    table_id = _table_id(req)
    tags: dict[str, dict] = {}
    for name, tag in open_dataset(ns, so, table_id).tags.list().items():
        version = getattr(tag, "version", None)
        if version is None and isinstance(tag, dict):
            version = tag.get("version")
        tags[name] = {"version": version, "manifest_size": getattr(tag, "manifest_size", None) or 0}
    # model_validate coerces the inner dicts into TagContents (not exported to name directly).
    return ListTableTagsResponse.model_validate({"tags": tags})


def create_tag(ns: LanceNamespace, so: StorageOptions, req: CreateTableTagRequest) -> CreateTableTagResponse:
    """Tag the given table version with a name."""
    open_dataset(ns, so, _table_id(req)).tags.create(req.tag, req.version)
    return CreateTableTagResponse()


def get_tag_version(
    ns: LanceNamespace, so: StorageOptions, req: GetTableTagVersionRequest
) -> GetTableTagVersionResponse:
    """Return the table version a tag points to."""
    version = open_dataset(ns, so, _table_id(req)).tags.get_version(req.tag)
    if version is None:
        raise InvalidInputError(f"tag {req.tag!r} not found")
    return GetTableTagVersionResponse(version=version)


def update_tag(ns: LanceNamespace, so: StorageOptions, req: UpdateTableTagRequest) -> UpdateTableTagResponse:
    """Move an existing tag to a new table version."""
    open_dataset(ns, so, _table_id(req)).tags.update(req.tag, req.version)
    return UpdateTableTagResponse()


def delete_tag(ns: LanceNamespace, so: StorageOptions, req: DeleteTableTagRequest) -> DeleteTableTagResponse:
    """Delete a tag from the table."""
    open_dataset(ns, so, _table_id(req)).tags.delete(req.tag)
    return DeleteTableTagResponse()
