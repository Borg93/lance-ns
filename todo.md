# Lance REST Catalog — Roadmap / TODO

Legend: ✅ done · ⛔ not started · 🔶 deferred

## Done
- ✅ Lance Namespace REST catalog (FastAPI over native pylance `DirectoryNamespace`, MinIO/S3).
- ✅ OIDC authn (PyJWT/JWKS), fail-closed.
- ✅ OpenFGA authz: op→`can_*` action relations, concentric owner⊇writer⊇reader,
  parent cascade (catalog→namespace→table), roles as `role:#assignee` subjects,
  `catalog:lance` root, `grant_on_create`/`seed_ownership`.
- ✅ Resilience: transient-aware retries; network errors → 503 (never escape as 500).
- ✅ Postgres (OpenFGA datastore) over sqlite.
- ✅ Auth e2e (`scripts/auth_e2e.sh`) + docker compose overlays; `docs/ARCHITECTURE.md`.
- ✅ Pluggable `CredentialVendor` scaffold — `app/core/vending.py` (ModeB / StaticPrefix / Sts).
- ✅ Maintenance read-only middleware — `app/api/maintenance.py` (default OFF).

## Decisions locked
- Secret manager: **OpenBao** (Vault-API / KV-v2 compatible).
- Prod object store *reality* = **Hitachi HCP** (no STS) — but NOT the long-term target.
- Data plane = **vending-first, pluggable `CredentialVendor`**:
  - HCP now → **Mode B** (server-mediated; no credential ever leaves the catalog) — most
    secure achievable on HCP. (Or static per-bucket keys if direct client I/O is required.)
  - S3-family target (MinIO dev / Ceph / S3) → **StsVendor** (short-TTL, per-table,
    read/write-scoped tokens) — the gold standard.
  - Presigned URLs ruled out (don't fit Lance's `object_store` LIST + many-GET dataset open).

## Next (in order)
1. ⛔ Pick the HCP plug: **Mode B (recommended)** vs static per-bucket keys; finish that one
   `CredentialVendor` impl (the others are scaffolded in `app/core/vending.py`).
2. ⛔ Wire `describe_table?vend_credentials=true` → `CredentialVendor`, OpenFGA-tiered
   (`can_read_data`→read creds, `can_write_data`→write). Keep default OFF.
3. ⛔ **OpenBao SecretStore** (KV v2): hold master/static storage creds + the OIDC client
   secret instead of plain env. (Lakekeeper `lakekeeper-secrets-kv2` is the template; OpenBao
   is Vault-API-compatible — use `hvac` or `httpx`.)
4. ⛔ **lance-ray promotion + compaction jobs** (bronze→silver→gold) on the KubeRay cluster;
   emit OpenLineage run events.
5. ⛔ **Routes-vs-spec conformance test** (assert FastAPI routes ⊆ lance-namespace spec ops).
6. 🔶 **Governance P1**: `project` type + 3-axis (teams × projects × layers); evolve the
   OpenFGA model with **versioned migrations** + a **reconcile-from-catalog** tool
   (Lakekeeper `migration.rs` / `reconcile.rs` patterns).
7. 🔶 **Lineage**: OpenLineage → Apache AGE (Postgres) graph + Cypher; emitted via an
   EventDispatcher hook (Lakekeeper `CloudEventBackend` template).
8. 🔶 **Dapr** (durable workflows) · **NATS** (events) · **OTel** (observability).

## Security checklist (apply throughout)
- Secrets in **OpenBao**, never env/files; rotate; least-privilege catalog credential.
- TLS client↔catalog and catalog↔storage; OIDC short-lived JWTs + JWKS rotation.
- Fail-closed authz; **audit every authz decision + data access** (feeds lineage).
- Network: catalog in a private subnet; object storage never public.
