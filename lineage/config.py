"""Lineage service settings (pydantic-settings, ``LINEAGE_*`` env vars)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LineageSettings(BaseSettings):
    """Config for the lineage service and its Apache AGE graph store."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    database_url: str = Field(
        default="postgresql://lineage:lineage@localhost:5433/lineage",
        alias="LINEAGE_DATABASE_URL",
    )
    graph: str = Field(default="lineage", alias="LINEAGE_GRAPH")


@lru_cache
def get_settings() -> LineageSettings:
    """Return the process-wide cached lineage settings."""
    return LineageSettings()
