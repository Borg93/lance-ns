"""Read sensitive secrets from the Dapr secret store at boot — so the store is actually CONSUMED.

The security audit flagged that the OpenBao/Dapr secret store was wired but never read: services still
took their secrets from plaintext pod env, making the integration decorative. When ``secrets_from_dapr``
is on, a service fetches its secret bundle from the local sidecar's secret store
(``GET /v1.0/secrets/<store>/<key>``) at startup and uses those values, with the plaintext env only as a
boot-time fallback (logged loudly) so a store outage can't hard-fail boot.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def fetch_dapr_secret(
    store: str, key: str, *, dapr_http_port: int = 3500, timeout: float = 5.0
) -> dict[str, str]:
    """Fetch a secret bundle ``{name: value}`` from the local Dapr secret store. Best-effort: returns
    ``{}`` (and logs) on any failure so the caller can fall back to env rather than crash at boot."""
    url = f"http://localhost:{dapr_http_port}/v1.0/secrets/{store}/{key}"
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
        log.warning("dapr_secret_unexpected_shape", extra={"store": store, "key": key})
        return {}
    except Exception as exc:  # noqa: BLE001 — boot must not hard-fail on a secret-store hiccup
        log.warning("dapr_secret_fetch_failed", extra={"store": store, "key": key, "error": str(exc)})
        return {}
