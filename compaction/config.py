"""Compaction service settings (pydantic-settings, ``COMPACTION_*`` env vars)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CompactionSettings(BaseSettings):
    """Config for the compaction/GC service + its S3 access to the lakehouse bucket."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # The Dapr cron binding name == the POST route the sidecar delivers ticks to (must match the
    # bindings.cron Component's metadata.name). Default matches the chart.
    binding_name: str = Field(default="compaction-cron", alias="COMPACTION_BINDING_NAME")
    # Datasets whose newest version is older than this are eligible for version GC (keep recent history).
    older_than_days: int = Field(default=7, ge=0, alias="COMPACTION_OLDER_THAN_DAYS")

    # --- S3 access to the Lance lakehouse bucket ----------------------------------------------------
    s3_endpoint: str = Field(default="http://localhost:9000", alias="COMPACTION_S3_ENDPOINT")
    s3_access_key_id: str = Field(default="rustfsadmin", alias="COMPACTION_S3_ACCESS_KEY_ID")
    # Default "" so the chart can omit the plaintext env when the store is the source; apply_dapr_secrets
    # fails closed if neither the store nor env provides it (the audit's secret-consumption fix — the
    # compaction pod is a real S3 consumer (compacts/GCs the lakehouse), so it must NOT ship the key plain).
    s3_secret_access_key: str = Field(default="", alias="COMPACTION_S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="lance-catalog", alias="COMPACTION_S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="COMPACTION_S3_REGION")

    # --- Secret consumption from the Dapr secret store (OpenBao) — symmetric with catalog + lineage.
    # When on, the S3 secret comes from the store at boot (NOT plaintext env); fails closed if absent.
    secrets_from_dapr: bool = Field(default=False, alias="COMPACTION_SECRETS_FROM_DAPR")
    dapr_secret_store: str = Field(default="lance-secrets", alias="COMPACTION_DAPR_SECRET_STORE")
    dapr_secret_key: str = Field(default="lance", alias="COMPACTION_DAPR_SECRET_KEY")
    dapr_secret_s3_field: str = Field(default="rustfs-secret-key", alias="COMPACTION_DAPR_SECRET_S3_FIELD")

    def storage_options(self) -> dict[str, str]:
        """The Lance ``storage_options`` for opening datasets on the (HTTP) S3 endpoint."""
        return {
            "endpoint": self.s3_endpoint,
            "access_key_id": self.s3_access_key_id,
            "secret_access_key": self.s3_secret_access_key,
            "region": self.s3_region,
            "allow_http": "true",
        }


@lru_cache
def get_settings() -> CompactionSettings:
    """The process-wide compaction settings (read once from env)."""
    return CompactionSettings()


def apply_dapr_secrets(settings: CompactionSettings) -> None:
    """Consume the S3 secret from the Dapr secret store (OpenBao) and set it on ``settings`` in place, as
    the SOLE source — no plaintext fallback when the store is meant to provide it. Fails closed if neither
    the store nor env yields a secret. No-op (and no Dapr import) when ``secrets_from_dapr`` is off.
    Symmetric with lineage.config.apply_dapr_secrets / the catalog lifespan."""
    if not settings.secrets_from_dapr:
        return
    from app.core.secrets import fetch_dapr_secret

    bundle = fetch_dapr_secret(settings.dapr_secret_store, settings.dapr_secret_key)
    s3_secret = bundle.get(settings.dapr_secret_s3_field)
    if s3_secret:
        settings.s3_secret_access_key = s3_secret
    elif not settings.s3_secret_access_key:
        raise RuntimeError(
            f"S3 secret unavailable from Dapr store {settings.dapr_secret_store!r}/"
            f"{settings.dapr_secret_key!r} and no env fallback — failing closed"
        )
