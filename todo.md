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
- ✅ Auth e2e + docker compose overlays; `docs/ARCHITECTURE.md`.
- ✅ Pluggable `CredentialVendor` scaffold — `app/core/vending.py` (ModeB / StaticPrefix / Sts).
- ✅ Maintenance read-only middleware — `app/api/maintenance.py` (default OFF).
- ✅ **Lineage service (incoming)** — `lineage/`: OpenLineage ingest → Apache AGE graph,
  `upstream/downstream/producers/graph`; dataset name = catalog `table:<id>`. Unit + e2e tested.
  ⚠️ NOT YET: read-side authz (endpoints open) · deployed image · async ingest.

## Decisions locked
- Secret manager: **OpenBao** (Vault-API / KV-v2 compatible).
- Prod object store *reality* = **Hitachi HCP** (no STS) — but NOT the long-term target.
- Data plane = **vending-first, pluggable `CredentialVendor`**:
  - HCP now → **Mode B** (server-mediated; no credential ever leaves the catalog).
  - S3-family target (MinIO dev / Ceph / S3) → **StsVendor** (short-TTL, per-table scoped).
  - Presigned URLs ruled out (don't fit Lance `object_store` LIST + many-GET).
- Lineage = separate service sharing only the `table:<id>` identity (services never call
  each other); read-authz reuses the shared OpenFGA store (read-only) + IdP.

## Next (in order)
1. ⛔ **Lineage read-side authz** *(P0 — security; lineage's own top item)*: gate
   `upstream/downstream/producers/graph` with OIDC + OpenFGA `can_get_metadata` on
   `table:<id>`. Reuse the catalog's `OIDCVerifier` (`app/core/oidc.py`) + `fga.check`
   (`app/core/fga.py`). Decision: **in-service** (recommended) vs gateway gating.
2. ⛔ **lance-ray promotion + compaction jobs** (bronze→silver→gold) on the KubeRay cluster,
   using the Mode-B/vending data plane AND emitting OpenLineage to the lineage svc
   (`lineage/seed.py` is the emitter template). This is the medallion flow end-to-end.
3. ⛔ Finish the HCP **Mode-B** vendor + wire `describe_table?vend_credentials=true`
   (OpenFGA-tiered: `can_read_data`→read, `can_write_data`→write). Default OFF.
4. ⛔ **OpenBao SecretStore** (KV v2): master/static storage creds + OIDC client secret
   out of env. (Lakekeeper `lakekeeper-secrets-kv2` template; OpenBao is API-compatible.)
5. ⛔ **Deploy lineage**: `lineage-api` compose service + `COPY lineage` in the image.
6. ⛔ **Routes-vs-spec conformance test** (FastAPI routes ⊆ lance-namespace spec ops).
7. 🔶 **Governance P1**: `project` type + 3-axis (teams × projects × layers); evolve the
   OpenFGA model with versioned migrations + reconcile-from-catalog (Lakekeeper patterns).
8. 🔶 **Async lineage ingest** (jobs → NATS → consume) · **Dapr** workflows · **OTel**.

## Security checklist (apply throughout)
- Secrets in **OpenBao**, never env/files; rotate; least-privilege catalog credential.
- TLS client↔catalog and catalog↔storage; OIDC short-lived JWTs + JWKS rotation.
- Fail-closed authz; **audit every authz decision + data access** (lineage is the audit graph).
- Network: catalog + lineage in a private subnet; object storage never public.
- **Lineage reads must be authz-gated** (see Next #1) — they leak the data estate.
