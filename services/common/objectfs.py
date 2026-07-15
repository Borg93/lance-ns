"""Shared pyarrow-filesystem resolution for object-store-backed registries.

One home for the ``storage_options`` → ``pyarrow.fs`` translation that the outbox, the warehouse registry,
and the model registry all need: an ``s3://`` root builds an ``S3FileSystem`` from the lance-style options
(endpoint/keys/region, path-style, http-ok); anything else (a ``file://`` or bare local path — dev/tests)
resolves via the local filesystem, so every consumer round-trips without object storage in unit tests.
"""

from __future__ import annotations

import pyarrow.fs as pafs

StorageOptions = dict[str, str]


def fs_and_base(root_uri: str, storage_options: StorageOptions) -> tuple[pafs.FileSystem, str]:
    """Resolve ``(filesystem, base_path)`` for ``root_uri`` (base has no scheme and no trailing slash)."""
    if root_uri.startswith("s3://") and storage_options.get("endpoint"):
        scheme, _, host = storage_options["endpoint"].partition("://")
        fs = pafs.S3FileSystem(
            access_key=storage_options.get("access_key_id"),
            secret_key=storage_options.get("secret_access_key"),
            endpoint_override=host or storage_options["endpoint"],
            scheme=scheme or "http",
            region=storage_options.get("region", ""),
            allow_bucket_creation=True,
        )
        return fs, root_uri[len("s3://") :].rstrip("/")
    resolved, path = pafs.FileSystem.from_uri(root_uri)
    return resolved, path.rstrip("/")
