"""Application settings (pydantic-settings).

Produces the ``properties`` map for the native ``lance_namespace`` backend and
the ``storage_options`` for direct pylance access. All values come from
``LANCE_*`` environment variables; object-store credentials are required (no
silent fallback) so a misconfigured deployment fails fast at boot.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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
    # Allow blob-v2 columns to reference EXTERNAL objects outside the dataset root (Blob.from_uri) on
    # create. Default off for two reasons: (1) an external pointer's bytes live outside the lakehouse, so
    # Lance's version-aware GC can't protect them and a source delete dangles the pointer; (2) SSRF — the
    # client controls the pointer URI and the cascade's read_blobs would fetch it with the medallion
    # service's network position + creds, so an arbitrary URI (cloud metadata, internal host) becomes a
    # server-side read primitive. Enable only for a trusted producer; Lance's REGISTERED EXTERNAL BASES
    # (approved base paths) are the finer-grained alternative. Managed/inline blobs (bytes in) always work.
    allow_external_blobs: bool = Field(default=False, alias="LANCE_ALLOW_EXTERNAL_BLOBS")
    # The SAFER external-blob posture: a comma-separated allowlist of approved base URIs. External
    # ``Blob.from_uri`` pointers are accepted ONLY when they fall under one of these registered bases (Lance
    # ``initial_bases``), while ``allow_external_blob_outside_bases`` stays False — so a create can reference
    # a curated media bucket without opening the blanket outside-bases SSRF door. Empty = no external bases.
    external_blob_bases: str = Field(default="", alias="LANCE_EXTERNAL_BLOB_BASES")

    @property
    def external_blob_base_list(self) -> list[str]:
        """The registered external-blob base URIs (parsed from the comma-separated allowlist)."""
        return [b.strip() for b in self.external_blob_bases.split(",") if b.strip()]

    # #3-B Lance multi-base DATA distribution: a comma-separated ALLOWLIST of approved data-base URIs a
    # create may spread its fragments across (the Uber pattern — one table's data round-robins over N
    # buckets, manifest stays in the primary root, reads fan out). A per-request ``data_base`` MUST be on
    # this list — a caller can never point a base at an arbitrary bucket (data-exfil / rogue-write door).
    # Empty (default) = the feature is off and every create is byte-identical to today.
    # INVARIANT (operator's responsibility): every base here MUST share the catalog's S3 endpoint + creds.
    # The read path vends only the top-level storage_options to all bases, so a base on a different endpoint
    # or needing different creds would accept writes but be UNREADABLE. (See dataplane._write_blob.)
    multibase_data_bases: str = Field(default="", alias="LANCE_MULTIBASE_DATA_BASES")

    @property
    def multibase_data_base_list(self) -> list[str]:
        """The approved multi-base data-distribution base URIs (parsed from the comma-separated allowlist)."""
        return [b.strip() for b in self.multibase_data_bases.split(",") if b.strip()]

    # #3-A per-warehouse physical multi-tenancy (admin control plane). When enabled, an admin API
    # (POST /v1/warehouses) provisions a physically separate S3 bucket per warehouse and binds top-level
    # namespaces to it, so a table under a bound namespace lands in that warehouse's bucket (not the shared
    # `root`). Default OFF: the request path is unchanged (no binding lookups) for single-bucket deployments;
    # the chart turns it on for the catalog. Additive + backward-compatible — an unbound namespace always
    # routes to the default `root`. The warehouse REGISTRY (records + bindings) lives under `control_root`.
    warehouses_enabled: bool = Field(default=False, alias="LANCE_WAREHOUSES_ENABLED")
    control_root: str = Field(default="", alias="LANCE_CONTROL_ROOT")

    # #17 model registry (candidate→blessed promotion). Each model's Lance registry dataset lives at
    # ``<models_root>/<model>`` — the medallion trainer writes it DIRECTLY there (registry_uri_for), so the
    # catalog can NOT reach it through native namespace resolution (that would drop the ``/medallion/``
    # prefix): the promote/describe endpoints open it by EXPLICIT URI. Defaults to ``<root>/medallion/models``
    # so a single-bucket deploy needs no extra config; override only when the registry is zoned elsewhere.
    # INVARIANT (operator's): this root MUST share the catalog's S3 endpoint + creds — the read path vends
    # only ``storage_options()`` (same constraint as multibase_data_bases).
    models_registry_root: str = Field(default="", alias="LANCE_MODELS_REGISTRY_ROOT")

    @property
    def registry_root(self) -> str:
        """Where warehouse records + namespace bindings live (defaults to the catalog `root` bucket)."""
        return self.control_root or self.root

    @property
    def models_root(self) -> str:
        """Root for per-model registry datasets (defaults to ``<root>/medallion/models``)."""
        return self.models_registry_root.rstrip("/") or f"{self.root.rstrip('/')}/medallion/models"

    def model_uri(self, model: str) -> str:
        """The explicit Lance-dataset URI for one model's registry: ``<models_root>/<model>``."""
        return f"{self.models_root}/{model}"

    # Object store (MinIO / S3). Credentials are required — no default — so a
    # missing secret fails loudly at startup instead of silently using a default.
    s3_endpoint: str = Field(default="http://minio:9000", alias="LANCE_S3_ENDPOINT")
    s3_access_key_id: str = Field(alias="LANCE_S3_ACCESS_KEY_ID")
    # Optional default: with secrets_from_dapr on, the secret comes from the store (no plaintext env), and
    # the lifespan fails closed if neither the store nor env provides it.
    s3_secret_access_key: SecretStr = Field(default=SecretStr(""), alias="LANCE_S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="LANCE_S3_REGION")
    s3_allow_http: bool = Field(default=True, alias="LANCE_S3_ALLOW_HTTP")
    s3_virtual_hosted: bool = Field(default=False, alias="LANCE_S3_VIRTUAL_HOSTED")

    # Secret consumption — when on, read the sensitive S3 secret from the Dapr secret store (OpenBao) at
    # boot instead of trusting plaintext env (the audit's 'wired but never read' fix). The store is then
    # the STRICT sole source: the chart omits the plaintext secret from pod env, and a store miss FAILS
    # CLOSED at boot (no env fallback) — matching the module docstring's "no silent fallback".
    secrets_from_dapr: bool = Field(default=False, alias="LANCE_SECRETS_FROM_DAPR")
    dapr_secret_store: str = Field(default="lance-secrets", alias="LANCE_DAPR_SECRET_STORE")
    dapr_secret_key: str = Field(default="lance", alias="LANCE_DAPR_SECRET_KEY")
    dapr_secret_s3_field: str = Field(default="rustfs-secret-key", alias="LANCE_DAPR_SECRET_S3_FIELD")

    # OIDC authentication (opt-in). When disabled, all routes are open. When
    # enabled, every /v1 route requires a valid bearer token from the issuer.
    oidc_enabled: bool = Field(default=False, alias="LANCE_OIDC_ENABLED")
    oidc_issuer: str | None = Field(default=None, alias="LANCE_OIDC_ISSUER")
    oidc_audience: str | None = Field(default=None, alias="LANCE_OIDC_AUDIENCE")
    oidc_cache_ttl: int = Field(default=3600, alias="LANCE_OIDC_CACHE_TTL")
    # Clock-skew leeway (seconds) for exp/iat checks, and an explicit opt-in to accept
    # an http:// issuer/JWKS (needed only for the local Dex dev IdP — never in prod).
    oidc_leeway: int = Field(default=60, alias="LANCE_OIDC_LEEWAY")
    oidc_allow_insecure: bool = Field(default=False, alias="LANCE_OIDC_ALLOW_INSECURE")

    # OpenFGA authorization (opt-in; requires OIDC for the user identity). When
    # store/model ids are unset, the app provisions them at startup (dev/e2e);
    # in production, provision once and pin both ids.
    fga_enabled: bool = Field(default=False, alias="LANCE_FGA_ENABLED")
    fga_api_url: str = Field(default="http://openfga:8080", alias="LANCE_FGA_API_URL")
    # Compliance audit trail (#41): emit a structured event on the dedicated `lance.audit` logger for every
    # security-relevant action — authn success/failure, authz allow/deny, credential vending — carrying
    # who/what/resource/outcome. Default on so a governed deployment records an audit trail out of the box;
    # set false to silence the stream. The events only carry a real subject when OIDC is on.
    audit_enabled: bool = Field(default=True, alias="LANCE_AUDIT_ENABLED")
    fga_store_id: str | None = Field(default=None, alias="LANCE_FGA_STORE_ID")
    fga_model_id: str | None = Field(default=None, alias="LANCE_FGA_MODEL_ID")
    # The FGA `warehouse:` root object (= the lakehouse bucket). Two roles: (1) every top-level
    # namespace links to it as its `parent`, so a grant here cascades into all namespaces/tables;
    # (2) it gates create-on-parent for top-level creation when fga_lock_root_create is on. Grant
    # admins owner/writer on it to bootstrap — OR attach it to a `project:` (and the project to a
    # `team:`) for the full Lakekeeper-style multi-tenant hierarchy (see services/common/auth/model.fga).
    # Must be a `warehouse:` object (the model's catalog-root type). Bootstrapped by an admin granting
    # owner/writer on it (there is no auto-seed) — only needed when fga_lock_root_create is on.
    fga_root_object: str = Field(default="warehouse:lance_catalog", alias="LANCE_FGA_ROOT_OBJECT")
    # When False (default), any authenticated caller may create a TOP-LEVEL namespace/
    # table and becomes its owner (the "users create their own workspaces" model). When
    # True, top-level creation also requires can_create_* on fga_root_object — an admin-gated
    # root that must be seeded to bootstrap. Nested creation always gates on the parent.
    fga_lock_root_create: bool = Field(default=False, alias="LANCE_FGA_LOCK_ROOT_CREATE")
    # Per-request OpenFGA client timeout (seconds). A hung authz call fails fast and is
    # retried rather than pinning a request worker. Wired into fga.make_client at startup.
    fga_timeout_seconds: float = Field(default=5.0, ge=0.1, alias="LANCE_FGA_TIMEOUT_SECONDS")

    # Data-plane credential vending (pluggable; see services/catalog/core/vending.py). Target = S3-compatible
    # storage (MinIO default, AWS S3, Ceph RGW, RustFS). Default "mode_b": server-mediated — no
    # credential leaves the catalog (the simplest, backend-agnostic default). "sts": STS AssumeRole
    # short-TTL per-table scoped tokens (the recommended path; MinIO/Ceph/AWS all implement STS).
    # "static": pre-provisioned per-bucket keys (simple setups / GCS interop).
    # Client-DIRECT is the default WRITE path via POST /{id}/commit (the catalog never proxies data bytes);
    # the vending MODE is the separate CREDENTIAL mechanism. Default `mode_b` (server_mediated) is safe on
    # any store; `web_identity`/`sts` are the SCOPED-credential upgrade and are opt-in because they need an
    # STS endpoint — WITHOUT one, boto3 resolves to the PUBLIC AWS STS endpoint and would POST the caller's
    # OIDC token there (audit 2026-07-14). The chart pairs `web_identity` with the endpoint + rustfs.oidc,
    # and `_validate_vending` below fails closed if the mode needs an endpoint that isn't set.
    vending_mode: Literal["mode_b", "static", "sts", "web_identity"] = Field(
        default="mode_b", alias="LANCE_VENDING_MODE"
    )
    vending_ttl_seconds: int = Field(default=900, ge=60, alias="LANCE_VENDING_TTL_SECONDS")
    s3_assume_role_arn: str | None = Field(default=None, alias="LANCE_S3_ASSUME_ROLE_ARN")
    s3_sts_endpoint: str | None = Field(default=None, alias="LANCE_S3_STS_ENDPOINT")

    # Maintenance: when true, reject mutating /v1 requests with 503 + Retry-After — for
    # zero-downtime model/schema migration windows. Default off (no-op).
    maintenance_read_only: bool = Field(default=False, alias="LANCE_MAINTENANCE_READ_ONLY")

    # Max request-body size (bytes) accepted on any route. The Arrow-IPC write endpoints buffer the whole
    # body in memory, so an unbounded POST (e.g. a multi-GB media blob pushed through the catalog instead of
    # the direct storage/vending path) OOMs the worker. The body-limit middleware rejects oversized bodies
    # with 413 BEFORE buffering, steering large payloads to the direct-write path (claim-check). Default
    # 256 MiB — generous for tabular batches + small inline blobs, bounded well under a worker's memory.
    max_body_bytes: int = Field(default=256 * 1024 * 1024, ge=1, alias="LANCE_MAX_BODY_BYTES")

    # Load-shedding (P5): cap CONCURRENT in-flight Arrow-IPC writes. Each buffers up to max_body_bytes, so N
    # concurrent = N × 256MiB — an OOM the memory tier only partly bounds. Over the cap → 429 (THROTTLING),
    # shed before the body is buffered. Generous default (rarely trips); 0 disables it (pre-P5 behavior).
    max_concurrent_writes: int = Field(default=16, ge=0, alias="LANCE_MAX_CONCURRENT_WRITES")

    # Lineage emission (opt-in). When enabled, the catalog emits an OpenLineage event to the lineage
    # service on a table write — fire-and-forget + best-effort, so the lineage service being down can
    # never block or fail a catalog write. The catalog is the only component that knows the verified
    # principal, so it is the authoritative source of "who created/changed a table" (author = token.sub).
    # Transport: ``http`` (direct POST — dev / external producers) or ``dapr`` (publish to the Dapr
    # ``pubsub.jetstream`` component via the local sidecar — durable, decoupled, the production path).
    lineage_emit_enabled: bool = Field(default=False, alias="LANCE_LINEAGE_EMIT_ENABLED")
    # Literal (like vending_mode) so pydantic validates the allowed set — one enum-setting idiom in this file.
    lineage_transport: Literal["http", "dapr"] = Field(default="http", alias="LANCE_LINEAGE_TRANSPORT")
    lineage_url: str | None = Field(default=None, alias="LANCE_LINEAGE_URL")
    lineage_emit_timeout_seconds: float = Field(
        default=5.0, ge=0.1, alias="LANCE_LINEAGE_EMIT_TIMEOUT_SECONDS"
    )
    lineage_job_namespace: str = Field(default="lance-catalog", alias="LANCE_LINEAGE_JOB_NAMESPACE")
    # Dapr pub/sub transport (used when lineage_transport == "dapr"). The component name is what the
    # sidecar resolves to NATS JetStream; the topic is versioned (a breaking schema change → a new .vN).
    dapr_pubsub: str = Field(default="lineage-pubsub", alias="LANCE_DAPR_PUBSUB")
    dapr_topic: str = Field(default="lineage.events.v1", alias="LANCE_DAPR_TOPIC")

    @model_validator(mode="after")
    def _validate_auth(self) -> Self:
        """Fail fast on incomplete auth / lineage configuration."""
        if self.oidc_enabled and not (self.oidc_issuer and self.oidc_audience):
            raise ValueError("LANCE_OIDC_ISSUER and LANCE_OIDC_AUDIENCE are required when OIDC is enabled")
        if self.fga_enabled and not self.oidc_enabled:
            raise ValueError(
                "LANCE_OIDC_ENABLED is required when LANCE_FGA_ENABLED is set (authz needs a user)"
            )
        if self.lineage_emit_enabled and self.lineage_transport == "http" and not self.lineage_url:
            raise ValueError("LANCE_LINEAGE_URL is required for the http lineage transport")
        return self

    @model_validator(mode="after")
    def _validate_vending(self) -> Self:
        """Fail closed on a token-egressing vending config (audit 2026-07-14).

        ``sts``/``web_identity`` build an STS client; without ``LANCE_S3_STS_ENDPOINT`` boto3 resolves the
        PUBLIC AWS STS endpoint and would POST the caller's OIDC token there. Refuse to boot instead — a
        clear misconfig error, never a silent third-party token egress.
        """
        if self.vending_mode in ("sts", "web_identity") and not self.s3_sts_endpoint:
            raise ValueError(
                f"LANCE_S3_STS_ENDPOINT is required for vending_mode={self.vending_mode!r} "
                "(else the caller's token would be sent to the public AWS STS endpoint)"
            )
        return self

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
    return Settings()  # required fields are read from the environment
