"""OpenFGA authorization dependency.

Router-level guard: when FGA is enabled it derives the resource object from the
request path (``namespace:<id>`` / ``table:<id>``) and the required relation from
the operation (read ops → ``reader``, mutations → ``writer``), then checks the
authenticated user against OpenFGA. A no-op when FGA is disabled.
"""

from __future__ import annotations

from fastapi import Request
from lance_namespace import PermissionDeniedError, UnauthenticatedError

from app.api.dependencies import SettingsDep
from app.api.security import CurrentToken
from app.core import fga

# Trailing path segment of read-only operations; everything else mutates → writer.
_READ_ACTIONS = frozenset(
    {
        "describe",
        "exists",
        "list",
        "query",
        "count_rows",
        "stats",
        "explain_plan",
        "analyze_plan",
        "version",
    }
)


async def authorize(request: Request, settings: SettingsDep, token: CurrentToken) -> None:
    """Enforce the caller's OpenFGA permission for this route (no-op when FGA is off)."""
    if not settings.fga_enabled:
        return
    client = getattr(request.app.state, "fga", None)
    if client is None:
        return
    if token is None:
        raise UnauthenticatedError("authentication required")

    object_id = request.path_params.get("id")
    if object_id is None:
        return  # collection / batch route — authentication already enforced

    path = request.url.path
    if path.startswith("/v1/namespace/"):
        resource = "namespace"
    elif path.startswith("/v1/table/"):
        resource = "table"
    else:
        return  # transaction / materialized_view — no resource object to check

    action = path.rstrip("/").rsplit("/", 1)[-1]
    relation = "reader" if action in _READ_ACTIONS else "writer"
    obj = f"{resource}:{object_id}"
    if not await fga.check(client, user=token.sub, relation=relation, obj=obj):
        raise PermissionDeniedError(f"{relation} required on {obj}")
