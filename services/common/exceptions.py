"""Error mapping for the REST layer.

Domain exceptions are the ``lance_namespace`` error hierarchy
(``LanceNamespaceError`` with a numeric ``.code``). This module maps those codes
to HTTP statuses and RFC 9457 Problem Details, and translates the native
backend's plain "not implemented" errors into ``UnsupportedOperationError`` so
unsupported operations surface as a spec-correct 501.
"""

from __future__ import annotations

from lance_namespace import ErrorCode, LanceNamespaceError, UnsupportedOperationError

_STATUS: dict[ErrorCode, int] = {
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

# The native dir backend raises plain (untyped) errors when an op is a genuine stub. We deliberately do
# NOT include marshalling hints like "is not an instance" here: that phrase is raised by a pydantic-vs-dict
# TypeError on a backed op, and laundering it into a 501 hides a real bug (the audit caught exactly this —
# create/describe/batch-delete versions were backed but appeared unsupported). Such errors now surface as 500.
_UNSUPPORTED_HINTS = ("not implemented", "not supported")


def status_for(code: int) -> int:
    """Map a numeric lance ``ErrorCode`` to an HTTP status, defaulting to 500."""
    try:
        return _STATUS.get(ErrorCode(code), 500)
    except ValueError:
        return 500


def as_unsupported_if_stub(exc: Exception) -> Exception:
    """Return an ``UnsupportedOperationError`` if ``exc`` signals a backend stub."""
    if isinstance(exc, LanceNamespaceError):
        return exc
    if any(hint in str(exc).lower() for hint in _UNSUPPORTED_HINTS):
        return UnsupportedOperationError(str(exc))
    return exc


def problem_detail(exc: LanceNamespaceError) -> tuple[int, dict[str, object]]:
    """Build (status, RFC 9457 problem+json body) for a domain error.

    A 5xx-mapped error uses a GENERIC ``detail`` — never ``str(exc)`` — so internals (paths, DSNs, driver
    messages) leak via logs only, not the response body. Client (4xx) errors keep their message: it is
    actionable and self-authored, not an internal leak.
    """
    status = status_for(int(exc.code))
    detail = "Internal Server Error" if status >= 500 else str(exc)
    body: dict[str, object] = {
        "type": f"https://lance.org/problems/{exc.__class__.__name__.lower()}",
        "title": exc.__class__.__name__,
        "status": status,
        "detail": detail,
        "code": int(exc.code),
        # Spec-0.9 ErrorResponse compatibility: `code` (required) + `error` (brief message). Kept
        # alongside the RFC 9457 fields so both problem-details and spec clients can parse us.
        "error": detail,
    }
    return status, body
