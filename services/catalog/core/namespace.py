"""Backend namespace construction and dataset resolution.

The REST server is an adapter over a native ``LanceNamespace`` backend
(``DirectoryNamespace`` on MinIO/S3 by default). ``open_dataset`` resolves a
table's storage location via the namespace and opens it with pylance — used by
the data-plane service for operations the native backend does not implement.
"""

from __future__ import annotations

import lance
from lance_namespace import (
    DescribeTableRequest,
    LanceNamespace,
    TableNotFoundError,
    connect,
)

from catalog.core.config import Settings


def build_namespace(settings: Settings) -> LanceNamespace:
    return connect(settings.impl, settings.namespace_properties())


def open_dataset(
    ns: LanceNamespace,
    storage_options: dict[str, str],
    table_id: list[str],
    *,
    version: int | None = None,
) -> lance.LanceDataset:
    resp = ns.describe_table(DescribeTableRequest(id=list(table_id), with_table_uri=True))
    location = getattr(resp, "table_uri", None) or getattr(resp, "location", None)
    if not location:
        raise TableNotFoundError(f"Table not found: {table_id}")
    return lance.dataset(location, storage_options=storage_options, version=version)
