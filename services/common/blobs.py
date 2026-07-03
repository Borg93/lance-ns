"""Blob-v2 column detection, shared across services.

Lance blob-v2 columns require file format ``>= 2.2`` and are identified by the
``lance.blob.v2`` Arrow extension type (registered when ``lance`` is imported).
These helpers let the catalog (create path) and the medallion compute (cascade)
recognise a blob column from an Arrow schema without materialising the payloads.

A blob-v2 column cannot be written at the default 2.1 format, so detecting one is
what routes a write onto the ``data_storage_version="2.2"`` path.
"""

from __future__ import annotations

import pyarrow as pa

#: Arrow extension name Lance stamps on a blob-v2 column (lance_docs/guide.md — Version Compatibility).
BLOB_V2_EXTENSION_NAME = "lance.blob.v2"


def is_blob_field(field: pa.Field) -> bool:
    """True when ``field`` is a Lance blob-v2 column (requires file format >= 2.2).

    Prefers the registered extension type's ``extension_name`` (present when ``lance`` is imported,
    which every service does) and falls back to the raw ``ARROW:extension:name`` field metadata for
    a schema decoded in a process where the extension is not registered.
    """
    if getattr(field.type, "extension_name", None) == BLOB_V2_EXTENSION_NAME:
        return True
    metadata = field.metadata or {}
    return metadata.get(b"ARROW:extension:name") == BLOB_V2_EXTENSION_NAME.encode()


def schema_has_blob(schema: pa.Schema) -> bool:
    """True when any field in ``schema`` is a Lance blob-v2 column."""
    return any(is_blob_field(field) for field in schema)


def blob_field_names(schema: pa.Schema) -> list[str]:
    """Names of the blob-v2 columns in ``schema`` (empty when there are none)."""
    return [field.name for field in schema if is_blob_field(field)]
