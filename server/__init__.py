"""Lance Namespace REST Catalog server (MinIO/S3-backed, storage-native).

A minimal, spec-aligned implementation of the Lance Namespace REST Catalog:

- ``server.namespace.S3DirNamespace`` -- a ``LanceNamespace`` backend that stores
  catalog metadata as marker objects on S3 (MinIO) and table data via pylance.
- ``server.app`` -- a FastAPI app mapping the spec's REST routes to that backend.
- ``server.auth`` -- the authN/authZ extension point (see module docstring).
"""
