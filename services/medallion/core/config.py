"""Medallion service settings (pydantic-settings, ``MEDALLION_*`` env vars).

The 3 movers run the **same** module (``medallion.mover:app``) and differ only by env — each is one stage
edge of the DAG (from-dataset → to-dataset, subscribe-topic → publish-topic). The producer
(``medallion.producer:app``) reads its own ``MEDALLION_RAW_*`` / producer fields. Both publish through the
shared Dapr ``pubsub.jetstream`` component the catalog/lineage already use.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MedallionSettings(BaseSettings):
    """Config for one medallion service (a mover stage, or the lance-ray producer)."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # --- shared Dapr wiring (same component + lineage topic as catalog/lineage) -----------------
    pubsub: str = Field(default="lineage-pubsub", alias="MEDALLION_PUBSUB")
    lineage_topic: str = Field(default="lineage.events.v1", alias="MEDALLION_LINEAGE_TOPIC")
    job_namespace: str = Field(default="lance-medallion", alias="MEDALLION_JOB_NAMESPACE")

    # --- mover stage config (the 3 movers share medallion.mover:app, differ only by these) ------
    from_dataset: str = Field(default="raw_events", alias="MEDALLION_FROM_DATASET")
    from_namespace: str = Field(default="raw", alias="MEDALLION_FROM_NAMESPACE")
    to_dataset: str = Field(default="bronze$events", alias="MEDALLION_TO_DATASET")
    to_namespace: str = Field(default="bronze", alias="MEDALLION_TO_NAMESPACE")
    operation: str = Field(default="ingest_events", alias="MEDALLION_OPERATION")
    author: str = Field(default="alice", alias="MEDALLION_AUTHOR")
    sub_topic: str = Field(default="medallion.raw", alias="MEDALLION_SUB_TOPIC")
    pub_topic: str = Field(default="", alias="MEDALLION_PUB_TOPIC")  # "" = terminal stage (gold)

    # --- Optional FGA gate (ReBAC enforcement) — the mover checks it is AUTHORIZED to produce the target
    # stage before emitting. The silver→gold mover checks `can_promote` (validator-only); the others check
    # `can_create_table` (writer). It checks as its own service identity, so a mover not granted the role
    # is DENIED — the cascade then ENFORCES the model, not just describes it. Off by default. -------------
    fga_enabled: bool = Field(default=False, alias="MEDALLION_FGA_ENABLED")
    fga_api_url: str = Field(default="http://openfga:8080", alias="MEDALLION_FGA_API_URL")
    fga_service_identity: str = Field(default="user:service-mover", alias="MEDALLION_FGA_SERVICE_IDENTITY")
    fga_required_action: str = Field(default="can_create_table", alias="MEDALLION_FGA_REQUIRED_ACTION")

    def fga_object(self) -> str:
        """The FGA object the mover must be authorized on — the target stage namespace."""
        return f"namespace:{self.to_namespace}"

    # --- producer (lance-ray) config — produces the raw dataset + the first trigger -------------
    raw_dataset: str = Field(default="raw_events", alias="MEDALLION_RAW_DATASET")
    raw_namespace: str = Field(default="raw", alias="MEDALLION_RAW_NAMESPACE")
    producer_operation: str = Field(default="lance_ray_ingest", alias="MEDALLION_PRODUCER_OPERATION")
    producer_author: str = Field(default="ray", alias="MEDALLION_PRODUCER_AUTHOR")
    raw_topic: str = Field(default="medallion.raw", alias="MEDALLION_RAW_TOPIC")


@lru_cache
def get_settings() -> MedallionSettings:
    """The process-wide medallion settings (read once from env)."""
    return MedallionSettings()
