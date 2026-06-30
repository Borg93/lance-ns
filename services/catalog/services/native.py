"""Delegate an operation to the native ``LanceNamespace`` backend.

Thin pass-through used by endpoints for every operation the native backend
implements. Absent methods and backend stubs are translated to
``UnsupportedOperationError`` (HTTP 501).
"""

from __future__ import annotations

from typing import Any

from common.exceptions import as_unsupported_if_stub
from lance_namespace import LanceNamespace, UnsupportedOperationError


def call(ns: LanceNamespace, method_name: str, *args: object) -> Any:
    """Invoke ``method_name`` on the backend, mapping absent/stub methods to 501.

    Returns the backend's response model verbatim (typed ``Any`` so endpoints can
    annotate the concrete response model for OpenAPI + serialization).
    """
    method = getattr(ns, method_name, None)
    if method is None:
        raise UnsupportedOperationError(f"Not supported: {method_name}")
    try:
        return method(*args)
    except Exception as exc:
        translated = as_unsupported_if_stub(exc)
        if translated is exc:
            raise
        raise translated from exc
