"""Unit tests for the OpenFGA resilience + id-canonicalisation fixes in common.fga.

These pin the audit-confirmed contracts WITHOUT touching the network:

* The dominant outage mode of the aiohttp transport (connection refused / DNS / read
  timeout) is raised as a raw ``aiohttp.ClientError`` / ``TimeoutError`` / ``OSError`` —
  NOT ``openfga_sdk.ApiException``. Those must be classified transient AND fail closed
  (``ServiceUnavailableError`` -> 503), on every read/write path, never escape as a 500.
* The root / delimiter-only id collapses to ``None`` so the grant and check paths agree.

Uses stdlib ``asyncio.run`` so no pytest-asyncio dependency is needed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import aiohttp
import pytest
from common import fga
from lance_namespace import ServiceUnavailableError
from openfga_sdk import OpenFgaClient
from openfga_sdk.client.models import ClientTuple


def test_is_transient_classifies_network_errors() -> None:
    """A down server (raw transport error) is transient; a definitive non-transport error is not."""
    assert fga._is_transient(aiohttp.ClientConnectionError("refused")) is True
    assert fga._is_transient(TimeoutError()) is True
    assert fga._is_transient(ConnectionRefusedError()) is True  # OSError subclass
    assert fga._is_transient(ValueError("not a transport error")) is False


class _DownClient:
    """Fake OpenFGA client whose every call raises a raw transport error (server down)."""

    async def check(self, *_a: object, **_k: object) -> object:
        raise aiohttp.ClientConnectionError("connection refused")

    async def batch_check(self, *_a: object, **_k: object) -> object:
        raise aiohttp.ClientConnectionError("connection refused")

    async def list_objects(self, *_a: object, **_k: object) -> object:
        raise TimeoutError

    async def list_users(self, *_a: object, **_k: object) -> object:
        raise aiohttp.ClientConnectionError("connection refused")

    async def write(self, *_a: object, **_k: object) -> object:
        raise ConnectionRefusedError


def _down() -> OpenFgaClient:
    """A down server cast to the SDK client type (the fake only needs the called methods)."""
    return cast(OpenFgaClient, _DownClient())


# One attempt + zero backoff keeps the test fast — enough to prove the except path catches
# a non-ApiException transport error and fails closed (rather than escaping as a 500).
def test_check_fails_closed_on_network_error() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga.check(
                _down(),
                user="alice",
                relation="can_read_data",
                obj="table:t",
                retry_attempts=1,
                retry_backoff_seconds=0.0,
                retry_max_backoff_seconds=0.0,
            )
        )


def test_batch_check_fails_closed_on_network_error() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga.batch_check(
                _down(),
                user="alice",
                relation="can_write_data",
                objects=["table:t"],
                retry_attempts=1,
                retry_backoff_seconds=0.0,
                retry_max_backoff_seconds=0.0,
            )
        )


def test_list_objects_fails_closed_on_network_error() -> None:
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga.list_objects(
                _down(),
                user="alice",
                relation="can_read_data",
                object_type="table",
                retry_attempts=1,
                retry_backoff_seconds=0.0,
                retry_max_backoff_seconds=0.0,
            )
        )


def test_list_users_fails_closed_on_network_error() -> None:
    # CONTRACT (#51): an access review must never answer "nobody" because OpenFGA was down — the
    # outage is a 503, exactly like every other read path.
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga.list_users(
                _down(),
                relation="can_read_data",
                obj="table:t",
                retry_attempts=1,
                retry_backoff_seconds=0.0,
                retry_max_backoff_seconds=0.0,
            )
        )


def test_list_users_extracts_subjects_and_wildcard() -> None:
    # The wrapper returns sorted bare subjects; a `user:*` public wildcard surfaces as "*" — an
    # access review must never hide a public grant.
    class _Client:
        async def list_users(self, body: object) -> object:
            del body
            return SimpleNamespace(
                users=[
                    SimpleNamespace(object=SimpleNamespace(type="user", id="bob"), wildcard=None),
                    SimpleNamespace(object=SimpleNamespace(type="user", id="alice"), wildcard=None),
                    SimpleNamespace(object=None, wildcard=SimpleNamespace(type="user")),
                ]
            )

    result = asyncio.run(fga.list_users(cast(OpenFgaClient, _Client()), relation="reader", obj="table:t"))
    assert result == ["*", "alice", "bob"]


def test_write_tuples_fails_closed_on_network_error() -> None:
    tuples = [ClientTuple(user="user:alice", relation="owner", object="table:t")]
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(
            fga.write_tuples(
                _down(),
                tuples,
                retry_attempts=1,
                retry_backoff_seconds=0.0,
                retry_max_backoff_seconds=0.0,
            )
        )


@pytest.mark.parametrize(
    ("table_id", "expected"),
    [
        ("$", None),  # delimiter-only root collapses to None (grant/check agree)
        ("", None),  # empty id
        ("db1", None),  # single top-level segment has no parent namespace
        ("a$b", "a"),  # nested table -> parent namespace
        ("a$b$c", "a$b"),  # two levels deep
    ],
)
def test_parent_namespace_id_root_and_nesting(table_id: str, expected: str | None) -> None:
    assert fga.parent_namespace_id(table_id, delimiter="$") == expected
