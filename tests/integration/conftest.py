"""Integration fixtures.

The backend namespace is a ``MagicMock(spec=LanceNamespace)`` injected via
dependency override, so these tests exercise *our* layer only — routing,
identifier parsing, request assembly, serialization, and error mapping — never
lance's actual operations.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from lance_namespace import LanceNamespace


@pytest.fixture
def fake_ns() -> MagicMock:
    return MagicMock(spec=LanceNamespace)


@pytest.fixture
def client(fake_ns: MagicMock) -> Iterator[TestClient]:
    # A local root keeps the lifespan's build_namespace cheap; requests use the
    # injected fake regardless (get_namespace is overridden).
    os.environ.setdefault("LANCE_REST_IMPL", "dir")
    os.environ.setdefault("LANCE_REST_ROOT", "/tmp/lance-test-root")
    # Object-store credentials are required by Settings; the local-dir backend
    # ignores them, but they must be set for Settings() to construct.
    os.environ.setdefault("LANCE_S3_ACCESS_KEY_ID", "test")
    os.environ.setdefault("LANCE_S3_SECRET_ACCESS_KEY", "test")

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.api.dependencies import get_namespace, get_storage_options
    from app.main import app

    app.dependency_overrides[get_namespace] = lambda: fake_ns
    app.dependency_overrides[get_storage_options] = lambda: {}
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
