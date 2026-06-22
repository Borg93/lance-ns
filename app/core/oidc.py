"""In-house OIDC ID-token verification (PyJWT + JWKS discovery).

Rolled in-house per the fastapi skill (no python-jose / wrapper lib): discover the
provider's ``.well-known/openid-configuration``, fetch + cache its JWKS, and verify
the token's signature / issuer / audience / expiry. Provider-agnostic — works with
Keycloak, Dex, Okta, Auth0, Entra, or Google by setting the issuer + audience.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from lance_namespace import UnauthenticatedError
from pydantic import BaseModel, ConfigDict

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


class IDToken(BaseModel):
    """OIDC ID-token claims; ``extra='allow'`` keeps provider-specific fields accessible."""

    model_config = ConfigDict(extra="allow")

    iss: str
    sub: str
    aud: str | list[str]
    exp: int
    iat: int


class OIDCVerifier:
    """Verify ID tokens against a provider, caching discovery + JWKS for ``cache_ttl`` seconds."""

    def __init__(self, issuer: str, audience: str, cache_ttl: int) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._ttl = cache_ttl
        self._cache: tuple[float, dict[str, Any], jwt.PyJWKClient] | None = None

    def _provider(self) -> tuple[dict[str, Any], jwt.PyJWKClient]:
        """Return the cached (discovery document, JWKS client), refreshing past the TTL."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache[0]) < self._ttl:
            return self._cache[1], self._cache[2]
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._issuer}{_DISCOVERY_SUFFIX}")
            response.raise_for_status()
            spec = response.json()
        jwk_client = jwt.PyJWKClient(spec["jwks_uri"], cache_jwk_set=True, max_cached_keys=16)
        self._cache = (now, spec, jwk_client)
        return spec, jwk_client

    def verify(self, token: str) -> IDToken:
        """Verify a bearer token and return its parsed claims, or raise ``UnauthenticatedError``."""
        spec, jwk_client = self._provider()
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=spec["id_token_signing_alg_values_supported"],
                audience=self._audience,
                issuer=spec["issuer"],
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            # Never leak the underlying JWT/crypto error to the client.
            raise UnauthenticatedError("Invalid or expired token") from exc
        return IDToken.model_validate(payload)
