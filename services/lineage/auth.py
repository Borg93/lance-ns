"""In-service authn / authz for the lineage read + ingest endpoints.

The lineage service owns the audit graph, so it must protect it itself (in-service, not
via a gateway). It mirrors the catalog's two-layer guard
(``app/api/security.py`` + ``app/api/fga_deps.py``) and **reuses the catalog's core** —
:class:`~app.core.oidc.OIDCVerifier` and :func:`app.core.fga.check` / ``batch_check`` — so
token verification and the OpenFGA check have one source of truth. The thin FastAPI authn +
filter dependencies are re-derived here because they bind to ``LineageSettings`` rather than
the catalog's ``Settings``. (Shared *library* code; the service makes no runtime call to the
catalog — it talks only to the IdP and the shared OpenFGA store, read-only.)

Three holes this closes (audit ``w8u4rc2tg``):

* **Reads** (``upstream``/``downstream``/``producers``/``graph``) leaked the entire data
  estate. Each is now gated on OpenFGA ``can_get_metadata`` of ``table:<dataset>`` — the
  same permission the catalog requires to ``describe`` that table.
* **Transitive disclosure.** A neighbor/graph read also returns *related* dataset names, so
  :class:`DatasetFilter` batch-checks each and drops the ones the caller may not see —
  mirroring the catalog's ``list_objects``-filtered enumerations.
* **Ingest** was unauthenticated and the run ``author`` was a producer-supplied facet, so
  provenance was forgeable. Ingest now requires a verified token and the author is taken
  from that token (:func:`enforce_author`) — the client-claimed facet is overwritten.

Default OFF (``LINEAGE_OIDC_ENABLED`` / ``LINEAGE_FGA_ENABLED``), exactly like the catalog;
production enables both. Fail-closed when enabled-but-unwired (503, never silent allow).
"""

from __future__ import annotations

import logging
from typing import Annotated

from common import fga
from common.oidc import IDToken, OIDCVerifier
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from lance_namespace import (
    PermissionDeniedError,
    ServiceUnavailableError,
    UnauthenticatedError,
)

from lineage.config import LineageSettings, get_settings
from lineage.models import RunEvent

log = logging.getLogger(__name__)

SettingsDep = Annotated[LineageSettings, Depends(get_settings)]

# auto_error=False: we raise UnauthenticatedError ourselves so 401s render as problem+json.
_bearer = HTTPBearer(auto_error=False, description="OIDC bearer token")
_CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def authenticate(request: Request, settings: SettingsDep, credentials: _CredentialsDep) -> IDToken | None:
    """Authenticate the request, returning the parsed token (or ``None`` when OIDC is off)."""
    if not settings.oidc_enabled:
        return None
    verifier: OIDCVerifier | None = getattr(request.app.state, "oidc", None)
    if verifier is None:
        # Enabled but no verifier wired (startup/discovery skew): fail closed, never open.
        raise ServiceUnavailableError("Authentication is enabled but unavailable")
    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError("Missing bearer token")
    return verifier.verify(credentials.credentials)


#: Token of the authenticated caller (``None`` when OIDC is disabled).
CurrentToken = Annotated[IDToken | None, Depends(authenticate)]


async def require_metadata_access(
    name: str, request: Request, settings: SettingsDep, token: CurrentToken
) -> None:
    """Gate a dataset read on OpenFGA ``can_get_metadata`` for ``<type>:<name>``.

    No-op when FGA is off. When on: fail closed if the client is unwired (503) or the
    request is unauthenticated (401), then deny (403) unless the caller has the same
    metadata-read permission the catalog requires to describe that table. ``fga.check``
    itself fails closed (503) on an OpenFGA outage rather than allowing.
    """
    if not settings.fga_enabled:
        return
    client = getattr(request.app.state, "fga", None)
    if client is None:
        raise ServiceUnavailableError("authorization service is not available")
    if token is None:
        raise UnauthenticatedError("authentication required")
    obj = f"{settings.fga_object_type}:{name}"
    if not await fga.check(client, user=token.sub, relation="can_get_metadata", obj=obj):
        log.info("access_denied", extra={"sub": token.sub, "relation": "can_get_metadata", "object": obj})
        raise PermissionDeniedError(f"can_get_metadata required on {obj}")


def enforce_author(event: RunEvent, token: IDToken | None) -> None:
    """Bind the run author to the *verified* principal — never trust the request body.

    When the request is authenticated, overwrite the ``author`` run facet with the token
    subject so a producer cannot self-assert someone else's identity (provenance forgery).
    When OIDC is off (dev/tests) the body-supplied author is left as-is.
    """
    if token is not None:
        event.run.facets["author"] = {"name": token.sub, "sub": token.sub}


class DatasetFilter:
    """Drop datasets the caller may not see from a lineage result (fail-closed).

    A neighbor/graph read returns *related* dataset names beyond the requested one; without
    filtering, one table grant would disclose the existence of every table in its lineage
    neighborhood. This batch-checks ``can_get_metadata`` (fail-closed: an OpenFGA outage →
    503) and returns only the authorized names — the lineage analogue of the catalog's
    ``list_objects``-filtered enumerations (``app/api/v1/endpoints/tables.py``). Pass-through
    when FGA is off (dev/tests).
    """

    def __init__(self, request: Request, settings: LineageSettings, token: IDToken | None) -> None:
        self._request = request
        self._settings = settings
        self._token = token

    async def visible(self, names: list[str]) -> set[str]:
        """Return the subset of ``names`` the caller may read (``can_get_metadata``)."""
        if not self._settings.fga_enabled or not names:
            return set(names)
        client = getattr(self._request.app.state, "fga", None)
        if client is None:
            raise ServiceUnavailableError("authorization service is not available")
        if self._token is None:
            raise UnauthenticatedError("authentication required")
        object_type = self._settings.fga_object_type
        allowed = await fga.batch_check(
            client,
            user=self._token.sub,
            relation="can_get_metadata",
            objects=[f"{object_type}:{n}" for n in names],
        )
        return {n for n in names if allowed.get(f"{object_type}:{n}")}


def get_dataset_filter(request: Request, settings: SettingsDep, token: CurrentToken) -> DatasetFilter:
    """Build the per-request dataset-visibility filter."""
    return DatasetFilter(request, settings, token)


FilterDep = Annotated[DatasetFilter, Depends(get_dataset_filter)]
