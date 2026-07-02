"""Column / schema endpoints (data-plane add/alter/drop + native backfill)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from lance_namespace import (
    AlterTableAddColumnsRequest,
    AlterTableAddColumnsResponse,
    AlterTableAlterColumnsRequest,
    AlterTableAlterColumnsResponse,
    AlterTableBackfillColumnsRequest,
    AlterTableBackfillColumnsResponse,
    AlterTableDropColumnsRequest,
    AlterTableDropColumnsResponse,
    UpdateFieldMetadataRequest,
    UpdateFieldMetadataResponse,
    UpdateTableSchemaMetadataRequest,
    UpdateTableSchemaMetadataResponse,
)

from catalog.api.dependencies import NamespaceDep, SettingsDep, StorageOptionsDep
from catalog.core.identifiers import parse_identifier
from catalog.services import dataplane, native

router = APIRouter(prefix="/v1/table", tags=["columns"])


@router.post("/{id}/add_columns", response_model_exclude_none=True)
def add_columns(
    id: str, body: AlterTableAddColumnsRequest, ns: NamespaceDep, settings: SettingsDep, so: StorageOptionsDep
) -> AlterTableAddColumnsResponse:
    """Add SQL-expression-computed columns to the table — wraps ``alter_table_add_columns``."""
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.add_columns(ns, so, body)


@router.post("/{id}/alter_columns", response_model_exclude_none=True)
def alter_columns(
    id: str,
    body: AlterTableAlterColumnsRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
) -> AlterTableAlterColumnsResponse:
    """Rename, re-type, or change nullability of existing columns — wraps ``alter_table_alter_columns``."""
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.alter_columns(ns, so, body)


@router.post("/{id}/drop_columns", response_model_exclude_none=True)
def drop_columns(
    id: str,
    body: AlterTableDropColumnsRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
) -> AlterTableDropColumnsResponse:
    """Drop the named columns from the table — wraps ``alter_table_drop_columns``."""
    body.id = parse_identifier(id, settings.delimiter)
    return dataplane.drop_columns(ns, so, body)


@router.post("/{id}/backfill_column", response_model_exclude_none=True)
def backfill_column(
    id: str, body: AlterTableBackfillColumnsRequest, ns: NamespaceDep, settings: SettingsDep
) -> AlterTableBackfillColumnsResponse:
    """Backfill values into columns via the native driver — wraps ``alter_table_backfill_columns``."""
    body.id = parse_identifier(id, settings.delimiter)
    return native.call(ns, "alter_table_backfill_columns", body)


@router.post("/{id}/update_field_metadata", response_model_exclude_none=True)
def update_field_metadata(
    id: str,
    body: UpdateFieldMetadataRequest,
    ns: NamespaceDep,
    settings: SettingsDep,
    so: StorageOptionsDep,
) -> UpdateFieldMetadataResponse:
    """Merge or replace per-field metadata for the given field paths — wraps ``update_field_metadata``."""
    table_id = parse_identifier(id, settings.delimiter)
    updates = [u.model_dump() for u in (body.updates or [])]
    return dataplane.update_field_metadata(ns, so, table_id, updates)


@router.post("/{id}/schema_metadata/update", response_model_exclude_none=True)
def update_table_schema_metadata(
    id: str, body: dict[str, Any], ns: NamespaceDep, settings: SettingsDep
) -> UpdateTableSchemaMetadataResponse:
    """Set the table's schema-level metadata map — wraps ``update_table_schema_metadata``."""
    # REST-only: the spec sends the metadata map directly, or wrapped as {"metadata": {...}}.
    nested = body.get("metadata")
    raw = nested if isinstance(nested, dict) else body
    metadata: dict[str, str] = {str(k): str(v) for k, v in raw.items()}
    req = UpdateTableSchemaMetadataRequest(id=parse_identifier(id, settings.delimiter), metadata=metadata)
    return native.call(ns, "update_table_schema_metadata", req)
