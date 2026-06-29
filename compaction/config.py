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
    s3_secret_access_key: str = Field(default="rustfsadmin", alias="COMPACTION_S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="lance-catalog", alias="COMPACTION_S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="COMPACTION_S3_REGION")

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
