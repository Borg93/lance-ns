"""In-house OIDC ID-token verification (PyJWT + JWKS discovery).

Rolled in-house per the fastapi skill (no python-jose / wrapper lib): discover the
provider's ``.well-known/openid-configuration``, fetch + cache its JWKS, and verify
the token's signature / issuer / audience / expiry. Provider-agnostic — works with
Keycloak, Dex, Okta, Auth0, Entra, or Google by setting the issuer + audience.

Security posture (see CHANGELOG in the task notes):

* **Local algorithm allowlist.** We never trust the provider's advertised
  ``id_token_signing_alg_values_supported`` blindly. We intersect it with a
  configured allowlist of asymmetric algorithms and pass only that safe set to
  ``jwt.decode``. ``none`` and the symmetric ``HS*`` family are rejected to defeat
  alg-confusion (an attacker signing ``HS256`` with the public key as the secret).
* **Clock-skew leeway.** A small, configurable ``leeway`` absorbs clock drift
  between us and the IdP while we still *require* ``exp`` / ``iat`` / ``aud``.
* **HTTPS enforcement.** Both the issuer and its ``jwks_uri`` must be HTTPS unless
  ``allow_insecure`` is set (needed only for the local Dex dev IdP over http).
* **Multiple accepted issuers.** ``issuer`` may be a single string or a list; each
  is discovered independently and a token is verified against the issuer whose
  discovery document matches the token's ``iss`` claim.
* **Opaque failures.** Every PyJWT / JWKS / crypto error is mapped to a generic
  ``UnauthenticatedError`` — we never leak library names or crypto detail.
"""

from __future__ import annotations

import time
from typing import NamedTuple
from urllib.parse import urlsplit

import httpx
import jwt
from lance_namespace import UnauthenticatedError
from pydantic import BaseModel, ConfigDict

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

#: Asymmetric signing algorithms we are willing to accept. Symmetric (``HS*``) and
#: ``none`` are deliberately excluded — accepting them with a public verification key
#: enables the classic alg-confusion forgery. Callers may further narrow this set,
#: but can never widen it past what the provider also advertises.
DEFAULT_ALLOWED_ALGORITHMS: tuple[str, ...] = (
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
)


class IDToken(BaseModel):
    """OIDC ID-token claims; ``extra='allow'`` keeps provider-specific fields accessible.

    Subclass this for provider-specific claims and validate against the subclass,
    e.g. for Okta::

        class OktaIDToken(IDToken):
            email: str
            groups: list[str] = []

    The required core claims (``iss``/``sub``/``aud``/``exp``/``iat``) are present on
    every conformant OIDC ID token; everything else is preserved via ``extra='allow'``.
    """

    model_config = ConfigDict(extra="allow")

    iss: str
    sub: str
    aud: str | list[str]
    exp: int
    iat: int


class _Discovery(BaseModel):
    """The subset of the provider's discovery document we rely on (boundary-validated)."""

    issuer: str
    jwks_uri: str
    id_token_signing_alg_values_supported: list[str] = []


class _Provider(NamedTuple):
    """A resolved provider: its discovery doc, JWKS client, and the safe algorithm set.

    An internal value bundle (not boundary input), so a ``NamedTuple`` is the right
    container — no per-construction validation, just an immutable typed triple.
    """

    spec: _Discovery
    jwk_client: jwt.PyJWKClient
    algorithms: list[str]


def _require_https(url: str, *, label: str, allow_insecure: bool) -> None:
    """Reject non-HTTPS ``url`` unless ``allow_insecure`` is set (dev-only escape hatch)."""
    if allow_insecure:
        return
    if urlsplit(url).scheme != "https":
        # Configuration error, surfaced at verify time as an opaque auth failure but
        # logged distinctly: an http issuer/jwks in production is a misconfiguration.
        raise UnauthenticatedError(
            f"OIDC {label} must use HTTPS (set LANCE_OIDC_ALLOW_INSECURE=true for dev IdPs)"
        )


class OIDCVerifier:
    """Verify ID tokens against one or more providers, caching discovery + JWKS per issuer.

    The verifier is constructed once at app startup and shared across requests. Each
    configured issuer is discovered lazily and cached for ``cache_ttl`` seconds.
    """

    def __init__(
        self,
        issuer: str | list[str],
        audience: str,
        cache_ttl: int,
        *,
        allowed_algorithms: tuple[str, ...] | list[str] = DEFAULT_ALLOWED_ALGORITHMS,
        leeway: int = 60,
        allow_insecure: bool = False,
    ) -> None:
        issuers = [issuer] if isinstance(issuer, str) else list(issuer)
        if not issuers:
            raise ValueError("OIDCVerifier requires at least one issuer")
        # Normalise (strip trailing slash) and de-duplicate while preserving order.
        self._issuers = list(dict.fromkeys(iss.rstrip("/") for iss in issuers))
        self._audience = audience
        self._ttl = cache_ttl
        self._leeway = leeway
        self._allow_insecure = allow_insecure
        # Keep the configured allowlist as an ordered, de-duplicated set of upper-cased
        # algorithm names so the intersection with the provider is deterministic.
        self._allowed = list(dict.fromkeys(alg.upper() for alg in allowed_algorithms))
        if not self._allowed:
            raise ValueError("OIDCVerifier requires a non-empty algorithm allowlist")
        # Per-issuer cache: configured_issuer -> (fetched_at, _Provider).
        self._cache: dict[str, tuple[float, _Provider]] = {}

    def _safe_algorithms(self, advertised: list[str]) -> list[str]:
        """Intersect the provider's advertised algorithms with our local allowlist.

        Order follows our allowlist (our preference), and the result excludes anything
        not asymmetric. An empty intersection means we cannot safely verify against this
        provider and the caller turns it into an auth failure.
        """
        advertised_upper = {alg.upper() for alg in advertised}
        # If the provider advertises nothing, fall back to our allowlist (RFC 8414 makes
        # the field OPTIONAL; many IdPs still only sign with RS256). This is still safe:
        # PyJWT enforces that the token's actual ``alg`` is in this asymmetric set.
        if not advertised_upper:
            return list(self._allowed)
        return [alg for alg in self._allowed if alg in advertised_upper]

    def _resolve(self, configured_issuer: str) -> _Provider:
        """Return the cached provider for ``configured_issuer``, refreshing past the TTL."""
        now = time.monotonic()
        cached = self._cache.get(configured_issuer)
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]

        _require_https(
            configured_issuer + _DISCOVERY_SUFFIX,
            label="issuer",
            allow_insecure=self._allow_insecure,
        )
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{configured_issuer}{_DISCOVERY_SUFFIX}")
            response.raise_for_status()
            spec = _Discovery.model_validate(response.json())

        # The discovery document's own ``issuer`` is authoritative for token validation;
        # it must match what we configured (defends against a tampered discovery doc).
        if spec.issuer.rstrip("/") != configured_issuer:
            raise UnauthenticatedError("OIDC discovery issuer mismatch")

        _require_https(spec.jwks_uri, label="jwks_uri", allow_insecure=self._allow_insecure)
        algorithms = self._safe_algorithms(spec.id_token_signing_alg_values_supported)
        if not algorithms:
            raise UnauthenticatedError("No mutually-supported OIDC signing algorithm")

        jwk_client = jwt.PyJWKClient(spec.jwks_uri, cache_jwk_set=True, max_cached_keys=16)
        provider = _Provider(spec=spec, jwk_client=jwk_client, algorithms=algorithms)
        self._cache[configured_issuer] = (now, provider)
        return provider

    def _provider_for(self, token: str) -> _Provider:
        """Select the configured provider whose issuer matches the token's ``iss`` claim.

        With a single issuer this is trivial. With several, we read the (still unverified)
        ``iss`` from the token to pick the right provider, then verification proves it.
        """
        if len(self._issuers) == 1:
            return self._resolve(self._issuers[0])
        try:
            claimed = jwt.decode(token, options={"verify_signature": False}).get("iss")
        except jwt.PyJWTError as exc:
            raise UnauthenticatedError("Invalid or expired token") from exc
        for configured in self._issuers:
            if isinstance(claimed, str) and claimed.rstrip("/") == configured:
                return self._resolve(configured)
        raise UnauthenticatedError("Unrecognized token issuer")

    def verify(self, token: str) -> IDToken:
        """Verify a bearer token and return its parsed claims, or raise ``UnauthenticatedError``."""
        provider = self._provider_for(token)
        try:
            signing_key = provider.jwk_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=provider.algorithms,
                audience=self._audience,
                issuer=provider.spec.issuer,
                leeway=self._leeway,
                # PyJWT does not verify the OIDC ``at_hash`` binding (it has no access
                # token to bind against), so there is nothing to disable — unlike
                # python-jose, no ``verify_at_hash`` option exists or is needed here.
                options={
                    "require": ["exp", "iat", "aud"],
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            # Never leak the underlying JWT/crypto error to the client.
            raise UnauthenticatedError("Invalid or expired token") from exc
        return IDToken.model_validate(payload)
