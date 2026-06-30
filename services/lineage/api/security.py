"""OIDC authentication dependency for the lineage read + ingest endpoints.

When OIDC is disabled (the default) this is a no-op and all routes stay open. When
enabled, it requires a verified bearer token and maps auth failures to RFC 9457
problem+json (401). It binds to ``LineageSettings`` but otherwise mirrors the catalog's
``app/api/security.py`` and reuses the catalog's :class:`~common.oidc.OIDCVerifier` — so
token verification has one source of truth.

Fail-closed invariant: if OIDC is enabled in settings but the verifier was never wired
onto ``app.state`` (startup/discovery skew), we raise ``ServiceUnavailableError`` (503)
rather than silently letting requests through.
"""

from __future__ import annotations

from typing import Annotated

from common.oidc import IDToken, OIDCVerifier
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from lance_namespace import ServiceUnavailableError, UnauthenticatedError

from lineage.api.dependencies import SettingsDep

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
