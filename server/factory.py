"""Build the backend namespace.

The REST server is an *adapter* (in the spec's terminology) over a native
``LanceNamespace`` backend. By default that backend is pylance's native,
Rust-backed ``DirectoryNamespace`` (``connect("dir", ...)``), rooted on MinIO/S3 —
it implements the operations; this server just exposes them over HTTP.
"""

from __future__ import annotations

from lance_namespace import LanceNamespace, connect

from server.settings import Settings


def build_namespace(settings: Settings) -> LanceNamespace:
    """Construct the native namespace backend from settings."""
    return connect(settings.impl, settings.namespace_properties())
