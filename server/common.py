"""Shared helpers for the REST routes.

Handles three things uniformly across every operation:

1. Identifier parsing — the ``{id}`` path segment is the ``$``-delimited Lance
   identifier (root namespace == the delimiter itself).
2. Request/response (de)serialization — JSON bodies (snake_case, matching the
   spec) are built into the generated ``lance_namespace`` request models and
   responses are dumped back to dicts. Missing models (version skew) → 501.
3. Calling the (blocking, Rust) namespace methods off the event loop and mapping
   ``LanceNamespaceError`` codes to HTTP status codes.
"""

from __future__ import annotations

from typing import Any

import lance_namespace as lns
from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from lance_namespace import (
    ErrorCode,
    InvalidInputError,
    LanceNamespaceError,
    UnsupportedOperationError,
)

ARROW_FILE = "application/vnd.apache.arrow.file"
ARROW_STREAM = "application/vnd.apache.arrow.stream"

# Lance error code -> HTTP status.
STATUS: dict[int, int] = {
    ErrorCode.UNSUPPORTED: 501,
    ErrorCode.NAMESPACE_NOT_FOUND: 404,
    ErrorCode.NAMESPACE_ALREADY_EXISTS: 409,
    ErrorCode.NAMESPACE_NOT_EMPTY: 409,
    ErrorCode.TABLE_NOT_FOUND: 404,
    ErrorCode.TABLE_ALREADY_EXISTS: 409,
    ErrorCode.TABLE_INDEX_NOT_FOUND: 404,
    ErrorCode.TABLE_INDEX_ALREADY_EXISTS: 409,
    ErrorCode.TABLE_TAG_NOT_FOUND: 404,
    ErrorCode.TABLE_TAG_ALREADY_EXISTS: 409,
    ErrorCode.TRANSACTION_NOT_FOUND: 404,
    ErrorCode.TABLE_VERSION_NOT_FOUND: 404,
    ErrorCode.TABLE_COLUMN_NOT_FOUND: 404,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.CONCURRENT_MODIFICATION: 409,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
    ErrorCode.INVALID_TABLE_STATE: 409,
    ErrorCode.TABLE_SCHEMA_VALIDATION_ERROR: 400,
    ErrorCode.THROTTLING: 429,
}


def get_ns(request: Request):
    return request.app.state.namespace


def get_delimiter(request: Request) -> str:
    return request.app.state.settings.delimiter


def parse_id(id_str: str, delimiter: str) -> list[str]:
    """Parse the ``$``-delimited identifier; the root namespace is the delimiter."""
    if id_str == delimiter or id_str == "":
        return []
    return id_str.split(delimiter)


def build_request(
    model_name: str, id_list: list[str] | None, body: dict | None = None, **overrides
):
    """Construct a generated request model from path id + JSON body + overrides.

    ``id_list=None`` is for id-less operations (batch create/commit).
    """
    model = getattr(lns, model_name, None)
    if model is None:
        raise UnsupportedOperationError(
            f"{model_name} is unavailable in this lance-namespace version"
        )
    data: dict[str, Any] = dict(body or {})
    if id_list is not None:
        data["id"] = id_list
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    from_dict = getattr(model, "from_dict", None)
    try:
        if callable(from_dict):
            obj = from_dict(data)
            if obj is not None:
                return obj
        return model(**data)
    except ValidationError as e:
        raise InvalidInputError(f"Invalid request for {model_name}: {e}") from e


def dump(obj: Any) -> Any:
    if obj is None:
        return {}
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump(by_alias=True, exclude_none=True)
    return obj


def get_storage_options(request: Request) -> dict[str, str]:
    return request.app.state.settings.storage_options()


# Native backends signal "this op isn't available" via these error-message hints
# (the dir backend raises plain errors, not typed UnsupportedOperationError).
_UNSUPPORTED_HINTS = ("not implemented", "not supported", "is not an instance")


async def _run(fn, *args):
    """Run a blocking call off the event loop, mapping backend errors to spec codes."""
    try:
        return await run_in_threadpool(fn, *args)
    except LanceNamespaceError:
        raise
    except Exception as e:  # noqa: BLE001
        if any(hint in str(e).lower() for hint in _UNSUPPORTED_HINTS):
            raise UnsupportedOperationError(str(e)) from e
        raise


async def call(ns, method_name: str, *args):
    """Invoke a (blocking) namespace method in a threadpool; 501 if absent/unsupported."""
    method = getattr(ns, method_name, None)
    if method is None:
        raise UnsupportedOperationError(f"Not supported: {method_name}")
    return await _run(method, *args)


async def json_op(
    request: Request,
    model_name: str,
    method_name: str,
    id_list: list[str],
    *,
    body: dict | None = None,
    **overrides,
) -> Any:
    """Standard JSON-in / JSON-out operation, delegated to the native backend."""
    ns = get_ns(request)
    req = build_request(model_name, id_list, body, **overrides)
    return dump(await call(ns, method_name, req))


async def dataplane_op(
    request: Request,
    model_name: str,
    fn,
    id_list: list[str],
    *,
    body: dict | None = None,
    **overrides,
) -> Any:
    """Operation implemented in-process via pylance (``fn(ns, storage_options, req)``).

    Used for ops the native backend stubs (update/delete/alter columns/tags).
    """
    ns = get_ns(request)
    so = get_storage_options(request)
    req = build_request(model_name, id_list, body, **overrides)
    return dump(await _run(fn, ns, so, req))
