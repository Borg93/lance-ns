"""Unit tests for :class:`app.core.oidc.OIDCVerifier.verify`.

These exercise the *real* verification path — signature, issuer, audience, expiry,
and the algorithm allowlist — with zero network. We generate an RSA keypair locally
(``cryptography``), sign tokens with PyJWT, and stub only the single IO boundary
(``OIDCVerifier._resolve``) so the verifier uses our local public key instead of a
fetched JWKS. Everything downstream of that boundary (``jwt.decode`` with the
allowlisted algorithms, issuer/audience/exp checks, opaque error mapping) runs for
real.

Mirrors the fastapi_oidc conftest approach: ``rsa.generate_private_key`` +
``jwt.encode`` against the matching public key.

Assumptions about the hardened verifier (already landed in ``app/core/oidc.py``):

* ``OIDCVerifier(issuer, audience, cache_ttl, *, allowed_algorithms=..., leeway=...,
  allow_insecure=...)`` — an asymmetric-only ``allowed_algorithms`` allowlist that is
  intersected with the provider's advertised algorithms.
* ``verify()`` returns an :class:`IDToken` on success and raises
  :class:`lance_namespace.UnauthenticatedError` (never a raw PyJWT error) on any
  failure: expired, wrong audience, wrong issuer, bad signature, or a disallowed
  algorithm such as ``HS256`` (alg-confusion defence).

The tests are written against this *public* behaviour. If the constructor keyword
changes name, only ``_make_verifier`` below needs updating; if the allowlist feature
were absent, ``test_verify_rejects_disallowed_algorithm_hs256`` documents the intended
contract and would fail loudly — which is the point of security tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lance_namespace import UnauthenticatedError

from app.core import oidc as oidc_module
from app.core.oidc import IDToken, OIDCVerifier, _Discovery, _Provider

ISSUER = "https://idp.example"
AUDIENCE = "lance"
KID = "test-key-1"


# --------------------------------------------------------------------------- #
# Local RSA keypair + a fake JWKS client returning its public key.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[Any, Any]:
    """A locally-generated RSA keypair; the private key signs, the public verifies."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def private_pem(rsa_keypair: tuple[Any, Any]) -> bytes:
    """PEM-encoded private key, the form PyJWT's ``encode`` accepts for RS256."""
    private_key, _ = rsa_keypair
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class _FakeSigningKey:
    """Stand-in for ``jwt.PyJWK`` — only the ``.key`` attribute is read by verify()."""

    def __init__(self, key: object) -> None:
        self.key = key


class _FakeJWKClient:
    """Returns our local public key regardless of the token's ``kid``.

    Real ``PyJWKClient`` selects a key by ``kid`` from a fetched JWKS; here there is a
    single key, so we hand it back unconditionally — the signature check itself proves
    whether the token was signed by the matching private key.
    """

    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._public_key)


def _make_verifier(
    rsa_keypair: tuple[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    advertised_algorithms: list[str] | None = None,
    **verifier_kwargs: Any,
) -> OIDCVerifier:
    """Build a verifier whose only IO boundary (``_resolve``) is stubbed to the local key.

    ``_resolve`` is the single method that touches the network (discovery + JWKS). We
    replace it with one that returns a :class:`_Provider` built from a controlled
    discovery doc and our fake JWKS client, while still running the verifier's *real*
    ``_safe_algorithms`` intersection so the allowlist is genuinely exercised.
    """
    _, public_key = rsa_keypair
    advertised = ["RS256"] if advertised_algorithms is None else advertised_algorithms

    verifier = OIDCVerifier(ISSUER, AUDIENCE, cache_ttl=3600, **verifier_kwargs)

    def fake_resolve(self: OIDCVerifier, configured_issuer: str) -> _Provider:
        spec = _Discovery(
            issuer=configured_issuer,
            jwks_uri=f"{configured_issuer}/jwks",
            id_token_signing_alg_values_supported=advertised,
        )
        # Run the verifier's real allowlist intersection so HS256/none can never slip in.
        algorithms = self._safe_algorithms(spec.id_token_signing_alg_values_supported)
        # _FakeJWKClient duck-types PyJWKClient's single used method; the model field is
        # typed concretely, so silence the static type only for this deliberate double.
        return _Provider(
            spec=spec,
            jwk_client=_FakeJWKClient(public_key),  # ty: ignore[invalid-argument-type]
            algorithms=algorithms,
        )

    monkeypatch.setattr(OIDCVerifier, "_resolve", fake_resolve)
    return verifier


def _b64url(raw: bytes) -> str:
    """base64url without padding, as used in JWS compact serialization."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _forge_hs256(claims: dict[str, Any], secret: bytes) -> str:
    """Hand-craft an HS256 token, bypassing PyJWT's encode-side asymmetric-key guard.

    Modern PyJWT refuses to *encode* HS256 with a PEM-looking key, but that guard only
    protects honest callers — a real attacker has no such constraint. We assemble the
    compact JWS directly so the test reflects the actual alg-confusion attack: HMAC the
    signing input with the RSA public-key bytes as the secret.
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{body}".encode()
    signature = _b64url(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def _claims(**overrides: Any) -> dict[str, Any]:
    """A valid claim set; tests override individual fields to make a token invalid."""
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "alice",
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    base.update(overrides)
    return base


def _sign(private_pem: bytes, claims: dict[str, Any]) -> str:
    """Sign ``claims`` as an RS256 JWT with the given PEM private key (honest path).

    Forgeries (HS256 alg-confusion, ``none``) are hand-assembled instead — see
    ``_forge_hs256`` and the ``none`` test — because PyJWT's ``encode`` refuses to
    produce them, exactly the constraint an attacker does not have.
    """
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})


# --------------------------------------------------------------------------- #
# Accept: a well-formed RS256 token.
# --------------------------------------------------------------------------- #


def test_verify_accepts_valid_rs256_token(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    token = _sign(private_pem, _claims())

    result = verifier.verify(token)

    assert isinstance(result, IDToken)
    assert result.sub == "alice"
    assert result.iss == ISSUER
    assert result.aud == AUDIENCE


def test_verify_preserves_extra_claims(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # extra='allow' keeps provider-specific claims (e.g. email/groups) accessible.
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    token = _sign(private_pem, _claims(email="alice@example.com", groups=["admin"]))

    result = verifier.verify(token)

    # extra='allow' surfaces unknown claims via the model dump (and as attributes at
    # runtime); assert through the dump so the access is ty/ruff-clean.
    dumped = result.model_dump()
    assert dumped["email"] == "alice@example.com"
    assert dumped["groups"] == ["admin"]


# --------------------------------------------------------------------------- #
# Reject: expired / wrong-aud / wrong-iss / bad-signature / disallowed-alg.
# Each must surface as an opaque UnauthenticatedError (never a raw PyJWT error).
# --------------------------------------------------------------------------- #


def test_verify_rejects_expired_token(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # exp well outside the verifier's leeway window.
    verifier = _make_verifier(rsa_keypair, monkeypatch, leeway=0)
    now = int(time.time())
    token = _sign(private_pem, _claims(iat=now - 600, exp=now - 300))

    with pytest.raises(UnauthenticatedError):
        verifier.verify(token)


def test_verify_rejects_wrong_audience(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    token = _sign(private_pem, _claims(aud="some-other-service"))

    with pytest.raises(UnauthenticatedError):
        verifier.verify(token)


def test_verify_rejects_wrong_issuer(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The configured/discovery issuer is ISSUER; a token claiming a different iss
    # must fail the issuer check inside jwt.decode.
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    token = _sign(private_pem, _claims(iss="https://evil.example"))

    with pytest.raises(UnauthenticatedError):
        verifier.verify(token)


def test_verify_rejects_bad_signature(rsa_keypair: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    # Sign with a DIFFERENT RSA private key; the verifier holds the original public key,
    # so the signature must not validate.
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_pem = attacker_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = _sign(attacker_pem, _claims())

    with pytest.raises(UnauthenticatedError):
        verifier.verify(token)


def test_verify_rejects_tampered_payload(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Flip a byte in the payload segment after signing — signature no longer matches.
    verifier = _make_verifier(rsa_keypair, monkeypatch)
    token = _sign(private_pem, _claims())
    header, payload, signature = token.split(".")
    tampered_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    tampered = f"{header}.{tampered_payload}.{signature}"

    with pytest.raises(UnauthenticatedError):
        verifier.verify(tampered)


def test_verify_rejects_disallowed_algorithm_hs256(
    rsa_keypair: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alg-confusion defence: an HS256 token signed with the public key is rejected.

    The classic forgery is to take the RSA *public* key (which is, well, public),
    treat its PEM bytes as an HMAC secret, and sign an HS256 token. A verifier that
    accepts HS256 would validate it. Our allowlist is asymmetric-only, so even though
    the provider here advertises HS256, the intersection drops it and jwt.decode is
    never offered HS256 — the token is rejected.
    """
    _, public_key = rsa_keypair
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # Provider advertises HS256 too, to prove the *local* allowlist (not the provider)
    # is what keeps us safe.
    verifier = _make_verifier(rsa_keypair, monkeypatch, advertised_algorithms=["RS256", "HS256"])
    forged = _forge_hs256(_claims(), secret=public_pem)

    with pytest.raises(UnauthenticatedError):
        verifier.verify(forged)


def test_verify_rejects_alg_none(rsa_keypair: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    # An unsigned ("alg": "none") token must never be accepted. Build it by hand —
    # the empty signature segment is the whole point of the "none" forgery.
    verifier = _make_verifier(rsa_keypair, monkeypatch, advertised_algorithms=["RS256", "none"])
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT", "kid": KID}).encode())
    body = _b64url(json.dumps(_claims()).encode())
    unsigned = f"{header}.{body}."

    with pytest.raises(UnauthenticatedError):
        verifier.verify(unsigned)


def test_verify_rejects_malformed_token(
    rsa_keypair: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _make_verifier(rsa_keypair, monkeypatch)

    with pytest.raises(UnauthenticatedError):
        verifier.verify("not-a-jwt")


def test_verify_error_is_opaque(
    rsa_keypair: tuple[Any, Any], private_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The mapped error must not leak the underlying PyJWT/crypto exception type or text.
    verifier = _make_verifier(rsa_keypair, monkeypatch, leeway=0)
    now = int(time.time())
    token = _sign(private_pem, _claims(iat=now - 600, exp=now - 300))

    with pytest.raises(UnauthenticatedError) as exc_info:
        verifier.verify(token)
    message = str(exc_info.value).lower()
    assert "expiredsignature" not in message
    assert "pyjwt" not in message
    assert "jwt" not in message


def test_module_exposes_asymmetric_only_default_allowlist() -> None:
    # Guardrail: the shipped default must never include a symmetric/none algorithm.
    default = {alg.upper() for alg in oidc_module.DEFAULT_ALLOWED_ALGORITHMS}
    assert default
    assert "HS256" not in default
    assert "HS384" not in default
    assert "HS512" not in default
    assert "NONE" not in default
    assert default <= {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
