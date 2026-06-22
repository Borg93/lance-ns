"""Server configuration via pydantic-settings.

Builds the ``properties`` map handed to the native ``lance.namespace`` backend
(``connect("dir", ...)``). Storage settings use the ``storage.*`` prefix
convention so they pass through to Lance's object-store layer (MinIO/S3).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # Catalog
    impl: str = Field(default="dir", alias="LANCE_REST_IMPL")
    root: str = Field(default="s3://lance-catalog", alias="LANCE_REST_ROOT")
    delimiter: str = Field(default="$", alias="LANCE_NS_DELIMITER")
    docs_enabled: bool = Field(default=True, alias="LANCE_REST_DOCS")

    # Object store (MinIO/S3)
    s3_endpoint: str = Field(default="http://minio:9000", alias="LANCE_S3_ENDPOINT")
    s3_access_key_id: str = Field(default="minioadmin", alias="LANCE_S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(
        default="minioadmin", alias="LANCE_S3_SECRET_ACCESS_KEY"
    )
    s3_region: str = Field(default="us-east-1", alias="LANCE_S3_REGION")
    s3_allow_http: bool = Field(default=True, alias="LANCE_S3_ALLOW_HTTP")
    s3_virtual_hosted: bool = Field(default=False, alias="LANCE_S3_VIRTUAL_HOSTED")

    def namespace_properties(self) -> dict[str, str]:
        """Properties for ``lance_namespace.connect(impl, properties)``."""
        return {
            "root": self.root,
            "storage.endpoint": self.s3_endpoint,
            "storage.access_key_id": self.s3_access_key_id,
            "storage.secret_access_key": self.s3_secret_access_key,
            "storage.region": self.s3_region,
            "storage.allow_http": str(self.s3_allow_http).lower(),
            "storage.virtual_hosted_style_request": str(self.s3_virtual_hosted).lower(),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
