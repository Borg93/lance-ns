"""Dual-auth for ``POST /produce`` (#64): the DAPR app-api-token OR a signed-in project admin.

The cascade head must never be forgeable (a raw-write event fabricates provenance), so the existing
service-to-service guard — the shared app-api-token — is kept UNCHANGED. This adds a SECOND, human door:
a signed-in OIDC user who holds ``can_administer`` on the project may trigger produce, so the web BFF can
forward the *user's* bearer and the web pod never holds the service token (no secrets-posture change).

Fail-closed at every step: no service token configured is dev-open (matching the old ``require_dapr_token``);
a matching Dapr token passes (service path, unchanged); otherwise an OIDC bearer is REQUIRED and must be
valid (else 401) AND resolve to a project admin (else 403), with an OpenFGA outage failing to 503 — never a
silent allow; a request carrying neither credential is 403.
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from common import fga
from common.oidc import OIDCVerifier
from fastapi import Header, HTTPException, Request
from lance_namespace import ServiceUnavailableError, UnauthenticatedError

from medallion.api.dependencies import FgaClientDep, SettingsDep


async def authorize_produce(
    request: Request,
    settings: SettingsDep,
    fga_client: FgaClientDep,
    dapr_api_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Allow EITHER the Dapr app-api-token (service) OR a signed-in project admin (OIDC + can_administer)."""
    expected = os.environ.get("APP_API_TOKEN")
    # Dev: no service token configured → open, exactly as require_dapr_token was a no-op.
    if not expected:
        return
    # Service-to-service path (UNCHANGED): a matching Dapr app-api-token.
    if dapr_api_token and secrets.compare_digest(dapr_api_token.encode(), expected.encode()):
        return
    # Human path: a signed-in project admin. Only when OIDC is configured + a verifier is wired.
    verifier: OIDCVerifier | None = getattr(request.app.state, "oidc", None)
    if settings.oidc_enabled and verifier is not None and authorization:
        scheme, _, raw = authorization.partition(" ")
        if scheme.lower() != "bearer" or not raw:
            raise HTTPException(status_code=401, detail="malformed bearer")
        try:
            token = verifier.verify(raw)
        except UnauthenticatedError:
            raise HTTPException(status_code=401, detail="invalid token") from None
        if fga_client is None:  # OIDC on but FGA unwired → fail closed, never an unauthorized trigger
            raise HTTPException(status_code=503, detail="authorization service is not available")
        obj = f"project:{settings.produce_admin_project}"
        try:
            allowed = await fga.check(fga_client, user=token.sub, relation="can_administer", obj=obj)
        except ServiceUnavailableError:
            raise HTTPException(status_code=503, detail="authorization service is not available") from None
        if allowed:
            return
        raise HTTPException(
            status_code=403, detail="produce needs project admin (can_administer) or the service token"
        )
    raise HTTPException(status_code=403, detail="invalid or missing produce credential")
