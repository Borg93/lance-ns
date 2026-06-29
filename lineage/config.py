"""Lineage service settings (pydantic-settings, ``LINEAGE_*`` env vars).

Auth is **opt-in and default OFF** (exactly like the catalog: ``LANCE_OIDC_ENABLED`` /
``LANCE_FGA_ENABLED``) so dev and tests run open; **production MUST enable both**. When
enabled the service reuses the catalog's ``OIDCVerifier`` + the **shared** OpenFGA store
(read-only) — so its FGA store/model ids must match the catalog's. Fail-closed config:
enabling a layer without the inputs it needs raises at startup, never silently opens.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LineageSettings(BaseSettings):
    """Config for the lineage service, its Apache AGE graph store, and its auth gate."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    database_url: str = Field(
        default="postgresql://lineage:lineage@localhost:5433/lineage",
        alias="LINEAGE_DATABASE_URL",
    )
    graph: str = Field(default="lineage", alias="LINEAGE_GRAPH")

    # --- OIDC (authn) — verifies the bearer token on reads + ingest --------------------
    oidc_enabled: bool = Field(default=False, alias="LINEAGE_OIDC_ENABLED")
    oidc_issuer: str | None = Field(default=None, alias="LINEAGE_OIDC_ISSUER")
    oidc_audience: str | None = Field(default=None, alias="LINEAGE_OIDC_AUDIENCE")
    oidc_cache_ttl: int = Field(default=3600, alias="LINEAGE_OIDC_CACHE_TTL")
    oidc_leeway: int = Field(default=60, alias="LINEAGE_OIDC_LEEWAY")
    oidc_allow_insecure: bool = Field(default=False, alias="LINEAGE_OIDC_ALLOW_INSECURE")

    # --- OpenFGA (authz) — reuses the catalog's store READ-ONLY -------------------------
    fga_enabled: bool = Field(default=False, alias="LINEAGE_FGA_ENABLED")
    fga_api_url: str = Field(default="http://openfga:8080", alias="LINEAGE_FGA_API_URL")
    fga_store_id: str | None = Field(default=None, alias="LINEAGE_FGA_STORE_ID")
    fga_model_id: str | None = Field(default=None, alias="LINEAGE_FGA_MODEL_ID")
    fga_timeout_seconds: float = Field(default=5.0, ge=0.1, alias="LINEAGE_FGA_TIMEOUT_SECONDS")
    # The FGA object type a Lance dataset maps to. A lineage Dataset node's ``name`` is the
    # catalog ``table:<id>``, so a read is gated on ``can_get_metadata`` of ``table:<name>``.
    fga_object_type: str = Field(default="table", alias="LINEAGE_FGA_OBJECT_TYPE")

    # --- Dapr pub/sub durable ingest (opt-in) — the catalog publishes to the Dapr pubsub.jetstream
    # component and the sidecar delivers each event to this service's subscription handler over HTTP, so
    # a lineage outage never loses provenance (the sidecar persists to NATS + redelivers per backOff).
    # The HTTP /api/v1/lineage endpoint stays for external producers. Off by default (HTTP is dev default).
    dapr_enabled: bool = Field(default=False, alias="LINEAGE_DAPR_ENABLED")
    dapr_pubsub: str = Field(default="lineage-pubsub", alias="LINEAGE_DAPR_PUBSUB")
    dapr_topic: str = Field(default="lineage.events.v1", alias="LINEAGE_DAPR_TOPIC")

    # --- Demo data peek (DEMO ONLY) — reads the real Lance datasets on S3 so the UI can show
    # what is changing in storage (schema/versions/rows). Off by default; never enable in prod.
    demo_data_enabled: bool = Field(default=False, alias="LINEAGE_DEMO_DATA_ENABLED")
    s3_endpoint: str | None = Field(default=None, alias="LINEAGE_S3_ENDPOINT")
    s3_access_key_id: str | None = Field(default=None, alias="LINEAGE_S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="LINEAGE_S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="LINEAGE_S3_REGION")
    s3_bucket: str = Field(default="lakehouse", alias="LINEAGE_S3_BUCKET")

    @model_validator(mode="after")
    def _validate_auth(self) -> Self:
        """Fail closed: a half-configured auth layer is a startup error, not open access."""
        if self.oidc_enabled and not (self.oidc_issuer and self.oidc_audience):
            raise ValueError("LINEAGE_OIDC_ENABLED requires LINEAGE_OIDC_ISSUER and LINEAGE_OIDC_AUDIENCE")
        if self.fga_enabled and not self.oidc_enabled:
            raise ValueError("LINEAGE_FGA_ENABLED requires LINEAGE_OIDC_ENABLED (need a verified subject)")
        if self.fga_enabled and not (self.fga_store_id and self.fga_model_id):
            raise ValueError(
                "LINEAGE_FGA_ENABLED requires LINEAGE_FGA_STORE_ID and LINEAGE_FGA_MODEL_ID "
                "(the catalog's store + model, shared read-only)"
            )
        return self


@lru_cache
def get_settings() -> LineageSettings:
    """Return the process-wide cached lineage settings."""
    return LineageSettings()


def storage_options(settings: LineageSettings) -> dict[str, str]:
    """Object-store options for reading Lance datasets directly (reconcile #23, demo peek).

    The same S3-compatible config the catalog writes with, so the lineage service reads the *actual*
    on-disk version to cross-check the graph. Empty strings let the object-store client fall back to
    its default credential chain (e.g. real AWS) when the ``LINEAGE_S3_*`` env vars are unset.
    """
    return {
        "endpoint": settings.s3_endpoint or "",
        "access_key_id": settings.s3_access_key_id or "",
        "secret_access_key": settings.s3_secret_access_key or "",
        "region": settings.s3_region,
        "allow_http": "true",
        "virtual_hosted_style_request": "false",
    }
