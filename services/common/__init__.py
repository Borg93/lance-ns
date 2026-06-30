"""Shared cross-cutting modules used by every lance-ns service.

These five modules (``secrets``, ``dapr_auth``, ``fga``, ``oidc``, ``exceptions``) are FastAPI-free (or
framework-light) infrastructure imported by the catalog, lineage, medallion and compaction services alike.
Extracted from the catalog's ``core/`` so no service depends on another service's package: every service
imports the shared pieces from ``common``, and ``common`` itself depends on none of the services.
"""
