"""Medallion service settings (pydantic-settings, ``MEDALLION_*`` env vars).

The 3 movers run the **same** module (``medallion.mover:app``) and differ only by env — each is one stage
edge of the DAG (from-dataset → to-dataset, subscribe-topic → publish-topic). The producer
(``medallion.producer:app``) reads its own ``MEDALLION_RAW_*`` / producer fields. Both publish through the
shared Dapr ``pubsub.jetstream`` component the catalog/lineage already use.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MedallionSettings(BaseSettings):
    """Config for one medallion service (a mover stage, or the lance-ray producer)."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    # --- shared Dapr wiring (same component + lineage topic as catalog/lineage) -----------------
    pubsub: str = Field(default="lineage-pubsub", alias="MEDALLION_PUBSUB")
    lineage_topic: str = Field(default="lineage.events.v1", alias="MEDALLION_LINEAGE_TOPIC")
    # Bound every Dapr publish so a hung sidecar raises TimeoutError → the mover's RETRY path fires (the
    # handler contract expects a prompt return), instead of pinning the worker until the ack window lapses.
    publish_timeout_seconds: float = Field(default=5.0, gt=0, alias="MEDALLION_PUBLISH_TIMEOUT_SECONDS")
    job_namespace: str = Field(default="lance-medallion", alias="MEDALLION_JOB_NAMESPACE")
    # Behind a Dapr sidecar? — when true, a mover fails closed at boot if the app-token is unset (its
    # /medallion-event route would otherwise be an open forged-trigger path). Symmetric with the lineage
    # service. Off in dev (no sidecar); the producer's plain-HTTP /produce carries no such route.
    dapr_enabled: bool = Field(default=False, alias="MEDALLION_DAPR_ENABLED")
    # Serve /docs + /openapi.json (default on for dev; prod sets false, like the catalog's LANCE_REST_DOCS).
    docs_enabled: bool = Field(default=True, alias="MEDALLION_DOCS")

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
    # BARE subject (no ``user:`` prefix) — ``common.fga.check`` adds ``user:`` itself, so ``user:service-*``
    # here would double-prefix (``user:user:service-*``) and the gate would always deny. Matches the
    # catalog's convention (it passes the bare OIDC sub to fga.check).
    fga_service_identity: str = Field(default="service-mover", alias="MEDALLION_FGA_SERVICE_IDENTITY")
    fga_required_action: str = Field(default="can_create_table", alias="MEDALLION_FGA_REQUIRED_ACTION")

    def fga_object(self) -> str:
        """The FGA object the mover must be authorized on — the target stage namespace."""
        return f"namespace:{self.to_namespace}"

    # --- Fake-Ray in-process compute (the lance-ray SEAM) — OFF by default (movers stay dummy-emitters).
    # When on, each stage does a REAL Lance write: the producer seeds raw_events; each mover reads its
    # upstream Lance dataset, applies a stage transform, and writes the downstream one — so the emitted
    # lineage carries the REAL version and the whole event-driven loop produces actual versioned data, not
    # just provenance. Same read→transform→write→version contract a distributed Ray Data job fills at rask;
    # here it runs in-process so the loop is end-to-end testable without a Ray cluster. (#25 / P1 #6 seam.)
    compute_enabled: bool = Field(default=False, alias="MEDALLION_COMPUTE_ENABLED")
    from_uri: str = Field(default="", alias="MEDALLION_FROM_URI")  # upstream Lance dataset (mover input)
    to_uri: str = Field(default="", alias="MEDALLION_TO_URI")  # downstream Lance dataset (mover output)

    # --- EVENT-DRIVEN real-Ray compute (opt-in, requires compute_enabled). When on, the mover submits its
    # stage transform as a `ray job submit` to the ray-lance cluster (via the Ray Jobs REST API, httpx-only —
    # no ray package in the mover image) IN RESPONSE TO its Dapr trigger, instead of the in-process fake-Ray
    # write. The submitted job (scripts/ray_stage_job.py, baked in the ray-lance image) reads upstream, stamps
    # the stage column across Ray workers, and writes downstream at 2.2 + stable row ids; the mover then reads
    # the written version/stats for the same lineage emit. OFF by default — fake-Ray stays the default path.
    # This is the production shape (KubeRay RayCluster at the rask merge; a raw Ray head on kind here).
    ray_enabled: bool = Field(default=False, alias="MEDALLION_RAY_ENABLED")
    ray_address: str = Field(default="http://ray-lance-head:8265", alias="MEDALLION_RAY_ADDRESS")
    ray_entrypoint: str = Field(
        default="python /home/ray/jobs/ray_stage_job.py", alias="MEDALLION_RAY_ENTRYPOINT"
    )
    ray_request_timeout_seconds: float = Field(
        default=10.0, ge=0.1, alias="MEDALLION_RAY_REQUEST_TIMEOUT_SECONDS"
    )
    ray_poll_interval_seconds: float = Field(default=2.0, gt=0, alias="MEDALLION_RAY_POLL_INTERVAL_SECONDS")
    # The mover BLOCKS its Dapr handler until the job finishes. Redelivery is safe (the submission id is
    # deterministic per (stage, token), so a redelivered trigger re-attaches to the same job — not a second
    # one), but a job that outlives the trigger stream's ack window (dapr-component backOff first value, 30s)
    # WILL be concurrently redelivered; that only wastes a duplicate poll (re-attach), it does not double-run
    # the job. For jobs expected to run much longer than the ack window, raise both together.
    ray_job_timeout_seconds: float = Field(default=180.0, gt=0, alias="MEDALLION_RAY_JOB_TIMEOUT_SECONDS")

    # --- Optional quality GATE — when on, after the compute writes the downstream dataset the mover runs
    # data-quality assertions on it (row_count > 0, key column non-null) and BLOCKS promotion on a failure:
    # the failed run + its dataQualityAssertions facet are still emitted (auditable in lineage), but the next
    # stage is NOT triggered, so a bad batch can't cascade. The automated *validator* half of governance —
    # FGA decides who MAY promote, quality decides if the DATA is good enough to. Requires compute (there is
    # no data to check otherwise). Off by default. ---------------------------------------------------------
    quality_enabled: bool = Field(default=False, alias="MEDALLION_QUALITY_ENABLED")
    quality_key_column: str = Field(default="id", alias="MEDALLION_QUALITY_KEY_COLUMN")

    # --- S3 access for the fake-Ray compute (only used when compute_enabled). Empty creds let the
    # object-store client fall back to its default chain (or a local path needs no creds at all). ---------
    s3_endpoint: str = Field(default="", alias="MEDALLION_S3_ENDPOINT")
    s3_access_key_id: str = Field(default="", alias="MEDALLION_S3_ACCESS_KEY_ID")
    # SecretStr so it's redacted in repr/model_dump (parity with the catalog) — .get_secret_value() to read.
    s3_secret_access_key: SecretStr = Field(default=SecretStr(""), alias="MEDALLION_S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="MEDALLION_S3_REGION")

    def storage_options(self) -> dict[str, str]:
        """Lance ``storage_options`` for the compute write — empty for a local path; S3 config otherwise."""
        if not self.s3_endpoint:
            return {}
        return {
            "endpoint": self.s3_endpoint,
            "access_key_id": self.s3_access_key_id,
            "secret_access_key": self.s3_secret_access_key.get_secret_value(),
            "region": self.s3_region,
            "allow_http": "true",
            # RustFS/MinIO require PATH-style addressing; without this lance signs the request
            # virtual-hosted-style and RustFS returns 403 SignatureDoesNotMatch (mirrors the catalog).
            "virtual_hosted_style_request": "false",
        }

    @model_validator(mode="after")
    def _compute_needs_s3_secret(self) -> Self:
        """Fail fast when compute writes to S3 but the secret is missing — else Lance 403s cryptically.

        The medallion is a dummy producer (the real compute is a Ray Data job at rask), so it has no OpenBao
        secret-fetch path like the catalog. When OpenBao is on (the chart default) the plaintext S3 secret is
        deliberately withheld from pod env, so turning compute on there leaves no secret and every Lance
        write fails with S3 ``SignatureDoesNotMatch``. Surface it at boot instead of at first produce.
        """
        if self.compute_enabled and self.s3_endpoint and not self.s3_secret_access_key.get_secret_value():
            raise ValueError(
                "MEDALLION_COMPUTE_ENABLED with an S3 endpoint but no MEDALLION_S3_SECRET_ACCESS_KEY. The "
                "medallion does not fetch S3 creds from OpenBao (unlike the catalog), so compute-on requires "
                "OpenBao off (helm --set openbao.enabled=false). The production compute is a Ray job at rask."
            )
        if self.ray_enabled and not self.compute_enabled:
            # ray submits the STAGE transform (from_uri -> to_uri); with compute off there is no data path and
            # the mover would silently fall through to the dummy version-1 emit. Fail fast, don't degrade.
            raise ValueError(
                "MEDALLION_RAY_ENABLED requires MEDALLION_COMPUTE_ENABLED — the Ray path submits the stage's "
                "read->transform->write, which the compute config (from/to URIs + S3) provides."
            )
        return self

    # --- producer (lance-ray) config — produces the raw dataset + the first trigger -------------
    raw_dataset: str = Field(default="raw_events", alias="MEDALLION_RAW_DATASET")
    raw_namespace: str = Field(default="raw", alias="MEDALLION_RAW_NAMESPACE")
    raw_uri: str = Field(
        default="", alias="MEDALLION_RAW_URI"
    )  # where the producer seeds raw_events (compute)
    producer_operation: str = Field(default="lance_ray_ingest", alias="MEDALLION_PRODUCER_OPERATION")
    producer_author: str = Field(default="ray", alias="MEDALLION_PRODUCER_AUTHOR")
    raw_topic: str = Field(default="medallion.raw", alias="MEDALLION_RAW_TOPIC")

    # --- media ingest head (multimodal §9) — POST /ingest-media lands external media as bronze blobs and
    # triggers the media chain. The head reads an external S3 source prefix through the provider-agnostic
    # SourceAdapter seam (a real deployment points bucket/prefix at IIIF/GCS/HF exports; the demo seeds
    # sample PNGs there first). Requires compute (there is no dummy media): media_bronze_uri is where the
    # bronze blob-v2 table lands; the trigger on media_topic drives the media mover (bronze -> silver
    # derive). Empty media_bronze_uri = the media head is off (POST /ingest-media -> 409). ----------------
    # The media lane gets its OWN namespaces (bronze-media → silver-media): the chart derives each
    # mover's from/to URI from the NAMESPACE (s3://<bucket>/medallion/<namespace>), so reusing the events
    # chain's bronze/silver would collide with bronze$events / silver$features on the same paths.
    media_source_bucket: str = Field(default="", alias="MEDALLION_MEDIA_SOURCE_BUCKET")
    media_source_prefix: str = Field(default="media-src/batch", alias="MEDALLION_MEDIA_SOURCE_PREFIX")
    media_bronze_uri: str = Field(default="", alias="MEDALLION_MEDIA_BRONZE_URI")
    media_bronze_dataset: str = Field(default="bronze-media$objects", alias="MEDALLION_MEDIA_BRONZE_DATASET")
    media_bronze_namespace: str = Field(default="bronze-media", alias="MEDALLION_MEDIA_BRONZE_NAMESPACE")
    media_topic: str = Field(default="medallion.media", alias="MEDALLION_MEDIA_TOPIC")
    # Seed two deterministic sample PNGs into the source prefix before ingesting (the demo's stand-in for
    # an external media drop). Prod points the bucket/prefix at real media and turns this off.
    media_seed_samples: bool = Field(default=True, alias="MEDALLION_MEDIA_SEED_SAMPLES")


@lru_cache
def get_settings() -> MedallionSettings:
    """The process-wide medallion settings (read once from env)."""
    return MedallionSettings()
