"""Render an Arrow/Lance schema into OpenLineage ``SchemaDatasetFacet`` fields.

A blob-v2 column is labelled ``"blob"`` (not its verbose extension storage type), a fixed-size vector as
``"array<elem>"``, and binary as ``"binary"`` — so the lineage graph shows meaningful column types for
media tables (``payload : blob``, ``embedding : array<float>``, ``thumbnail : binary``) instead of the raw
pyarrow repr. Shared by the medallion emitter (WROTE-edge schema facet) and the lineage demo peek.
"""

from __future__ import annotations

import pyarrow as pa

from common.blobs import is_blob_field


def type_label(field: pa.Field) -> str:
    """A concise lineage type label for ``field`` — blob/vector/binary specialised, else the pyarrow repr."""
    if is_blob_field(field):
        return "blob"
    dtype = field.type
    if pa.types.is_fixed_size_list(dtype) or pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
        return f"array<{dtype.value_type}>"
    if pa.types.is_binary(dtype) or pa.types.is_large_binary(dtype):
        return "binary"
    return str(dtype)


def facet_fields(schema: pa.Schema) -> list[dict[str, str]]:
    """The ``fields`` of an OpenLineage ``SchemaDatasetFacet`` — ``[{"name", "type"}]`` per column."""
    return [{"name": field.name, "type": type_label(field)} for field in schema]
