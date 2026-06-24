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
