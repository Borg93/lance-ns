"""Application settings (pydantic-settings).

Produces the ``properties`` map for the native ``lance_namespace`` backend and
the ``storage_options`` for direct pylance access. All values come from
``LANCE_*`` environment variables; object-store credentials are required (no
silent fallback) so a misconfigured deployment fails fast at boot.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_STORAGE_PREFIX = "storage."


class Settings(BaseSettings):
    """Catalog + object-store configuration sourced from ``LANCE_*`` env vars."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # Catalog
    impl: str = Field(default="dir", alias="LANCE_REST_IMPL")
    root: str = Field(default="s3://lance-catalog", alias="LANCE_REST_ROOT")
    delimiter: str = Field(default="$", alias="LANCE_NS_DELIMITER")
    docs_enabled: bool = Field(default=True, alias="LANCE_REST_DOCS")

    # Object store (MinIO / S3). Credentials are required — no default — so a
    # missing secret fails loudly at startup instead of silently using a default.
    s3_endpoint: str = Field(default="http://minio:9000", alias="LANCE_S3_ENDPOINT")
    s3_access_key_id: str = Field(alias="LANCE_S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr = Field(alias="LANCE_S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="LANCE_S3_REGION")
    s3_allow_http: bool = Field(default=True, alias="LANCE_S3_ALLOW_HTTP")
    s3_virtual_hosted: bool = Field(default=False, alias="LANCE_S3_VIRTUAL_HOSTED")

    def namespace_properties(self) -> dict[str, str]:
        """Return properties for ``lance_namespace.connect(impl, properties)``."""
        return {
            "root": self.root,
            f"{_STORAGE_PREFIX}endpoint": self.s3_endpoint,
            f"{_STORAGE_PREFIX}access_key_id": self.s3_access_key_id,
            f"{_STORAGE_PREFIX}secret_access_key": self.s3_secret_access_key.get_secret_value(),
            f"{_STORAGE_PREFIX}region": self.s3_region,
            f"{_STORAGE_PREFIX}allow_http": str(self.s3_allow_http).lower(),
            f"{_STORAGE_PREFIX}virtual_hosted_style_request": str(self.s3_virtual_hosted).lower(),
        }

    def storage_options(self) -> dict[str, str]:
        """Return the ``storage.*`` properties with the prefix stripped, for pylance."""
        return {
            key[len(_STORAGE_PREFIX) :]: value
            for key, value in self.namespace_properties().items()
            if key.startswith(_STORAGE_PREFIX)
        }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""
    return Settings()  # ty: ignore[missing-argument]  # required fields are read from the environment
