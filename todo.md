# Lance REST Catalog — Roadmap / TODO

**Legend:** ✅ done · 🟡 in progress · ⛔ not started · 🔶 deferred
**Priority:** `P0` security/correctness blocker · `P1` needed for prod · `P2` later

> Reconciled with the grounded audit **`w8u4rc2tg`** (4 read-only auditors → adversarial
> verification → synthesis; **5/9 high-criticals confirmed**, all `file:line`-cited). Items tagged
> **✔audit** are verified against the real code. Caveat: the lineage authz items were real but
> currently **latent** — the lineage service is undeployed/unreachable today.
>
> **Update:** P0 #1 + #2 (lineage read/ingest authz) are now **implemented + adversarially
> reviewed** (audit `wi2l437mq`, verdict ship-with-nits; mediums fixed). Default OFF — prod must
> enable `LINEAGE_OIDC_ENABLED` + `LINEAGE_FGA_ENABLED`.

---

## Done (built + tested)
- ✅ Lance Namespace REST catalog — FastAPI over native pylance `DirectoryNamespace` (MinIO/S3).
- ✅ OIDC authn (PyJWT/JWKS), **fail-closed**.
- ✅ OpenFGA authz — op→`can_*` actions, concentric owner⊇writer⊇reader, parent cascade
  (`catalog→namespace→table`), roles as `role:#assignee`, `catalog:lance` root,
  `grant_on_create`/`seed_ownership`. Model at `app/auth/model.fga` (+ `.fga.yaml` tests).
- ✅ Resilience — transient-aware retries; network errors → 503 (never escape as 500).
- ✅ Postgres (OpenFGA datastore) over sqlite.
- ✅ Auth e2e + docker compose overlays; `docs/ARCHITECTURE.md`.
- ✅ Pluggable `CredentialVendor` scaffold — `app/core/vending.py` (ModeB / StaticPrefix / Sts).
- ✅ Read-only maintenance middleware — `app/api/maintenance.py` (default OFF).
- ✅ Lineage service (incoming) — `lineage/`: OpenLineage ingest → Apache AGE graph,
  `upstream/downstream/producers/graph`; dataset name = catalog `table:<id>`; injection-safe
  Cypher (agtype bind params). **Open holes below.**
- ✅ Interactive system diagram — `docs/system-diagram.html` + `docs/system-diagram.md`.
- ✅ **Lineage auth (P0 #1/#2)** — in-service OIDC + OpenFGA `can_get_metadata` gate on all reads
  (+ `batch_check` transitive-disclosure filtering via `DatasetFilter`) and ingest authn +
  verified-author binding; reuses the catalog's verifier/check. Default OFF, fail-closed.
  `lineage/auth.py`, `lineage/config.py`, `lineage/main.py` (reviewed by audit `wi2l437mq`).
- ✅ **Structured logging standardized** repo-wide (event-name + `extra=`, level discipline per
  `observability.md`) + authz-decision audit logging (`access_denied`) in catalog + lineage.
- ✅ **Catalog → lineage emission (P0 #3)** — table create emits OpenLineage with the verified author
  → `(:User)-[:CREATED]->(:Dataset)` + `GET /datasets/{id}/creator`. Default OFF, fire-and-forget.
- ✅ **Lineage service deployed** (`lineage-api`, P1 #8) + **governance demo/e2e** — `scripts/governance_demo.py`
  (narrated) + `tests/e2e/test_governance_e2e.py` (gated) + `scripts/governance_e2e.sh` over the full stack.

---

## Decisions locked
- **Secret manager:** OpenBao (Vault-API / KV-v2 compatible).
- **Prod object store reality = Hitachi HCP** (S3 API via boto3; **NOT** the long-term target).
- **Data plane = vending-first, pluggable `CredentialVendor`:**
  - MinIO/S3 target → **`StsVendor`** (short-TTL, per-table scoped) — the optimized path.
  - HCP → **`ModeBVendor`** (server-mediated; no credential leaves the catalog) or
    **`StaticPrefixVendor`** (per-bucket key from OpenBao) — pending HCP's real cred surface (audit).
  - Presigned URLs ruled out (don't fit Lance `object_store`: LIST + many-GET).
- **Credential / secret responsibility (least privilege)** — *this is why only the catalog
  touches OpenBao in the sketch; it is by design, not an omission:*
  - **Compute jobs (lance-ray) never read OpenBao for storage** — they receive short-TTL,
    table-scoped creds from the catalog via `describe_table?vend_credentials`. A compromised
    job leaks a ~15-min scoped token, not a durable vault key.
  - **Jobs authenticate to the catalog with workload identity** (KubeRay projected
    ServiceAccount / OIDC token) — no stored secret, so still no OpenBao dependency.
  - **OpenBao consumers = the CATALOG** (base storage cred for vending, OIDC client secret,
    OpenFGA + AGE DB creds) **and the LINEAGE svc** (AGE DB creds).
- **Lineage = separate service** sharing only the `table:<id>` identity (services never call
  each other); read + ingest authz reuse the shared OpenFGA store (read-only) + the IdP.

---

## Next (priority order)

### P0 — security / correctness (do first)
1. ✅ **Lineage READ authz** — `upstream/downstream/producers/graph` gated on OIDC +
   OpenFGA `can_get_metadata` on `table:<name>`, reusing the catalog's `OIDCVerifier` +
   `fga.check` (`lineage/auth.py`, `lineage/main.py`). Default OFF, fail-closed when enabled.
   **Plus** transitive-disclosure filtering: related/graph datasets the caller can't see are
   dropped via `fga.batch_check` (`DatasetFilter`), mirroring the catalog's `list_objects`
   filtering. *(audit `w8u4rc2tg` follow-up; reviewed by `wi2l437mq`.)* **Prod must set
   `LINEAGE_OIDC_ENABLED` + `LINEAGE_FGA_ENABLED`.**
2. ✅ **Lineage INGEST authz + verified author (anti-forgery)** — ingest requires a verified
   token (401 otherwise) and `enforce_author` binds `author` = `token.sub`, overwriting any
   body-claimed facet (`lineage/auth.py`, `lineage/main.py`). Tested end-to-end so deleting the
   bind regresses a test. *(Remaining: optional FGA authz that the producer may write the named
   outputs — attributable today, not yet output-scoped.)*
3. ✅ **Catalog emits lineage on create** with `author` = the verified `token.sub` — "who created
   the table" is now an audit fact: a `(:User)-[:CREATED]->(:Dataset)` edge, queryable at
   `GET /datasets/{id}/creator`. Fire-and-forget + best-effort (never blocks/fails a write), default
   OFF (`LANCE_LINEAGE_EMIT_ENABLED`), canonical id (lineage Dataset == OpenFGA object id).
   `app/core/lineage_emit.py`, `app/api/v1/endpoints/data.py`, `lineage/{models,repository,main}.py`.
   *(Remaining → P2: emit on insert/merge/delete/compaction + Lance-version linkage.)*
4. 🟡 **Identity-consistency** — the catalog now emits lineage via `fga.canonical_object_id`, so a
   catalog-created Dataset name == its OpenFGA object id under any delimiter. **Still TODO:** the
   `lineage/seed.py` demo emitter hardcodes `$`, and a byte-identical cross-axis test under a
   non-default delimiter. Touch: `lineage/config.py`, `lineage/seed.py` + a test.

### P1 — needed for prod
5. ⛔ **Finish HCP Mode-B vendor** + wire `describe_table?vend_credentials=true`
   (OpenFGA-tiered: `can_read_data`→read, `can_write_data`→write). Default OFF. `app/core/vending.py`, `app/api/v1/endpoints/data.py`.
   **Pin `LANCE_VENDING_MODE=mode_b` for HCP** and do **not** use `static` on HCP — HCP has no
   per-bucket keys, only the user's tenant-wide `md5(password)` identity key (audit). *(vending.py
   docstring corrected ✔audit.)*
6. ⛔ **lance-ray promotion + compaction jobs** (bronze→silver→gold) on the KubeRay cluster,
   using the Mode-B/vending data plane **and** emitting OpenLineage (template: `lineage/seed.py`).
   This is the medallion flow end-to-end.
7. ⛔ **OpenBao SecretStore** (KV v2): move catalog base storage cred + OIDC client secret +
   OpenFGA/AGE DB creds out of env; lineage AGE DB creds. lance-ray = **workload identity** (no Bao).
8. ✅ **Deploy lineage** — `lineage-api` service (`.docker/docker-compose.governance.yml`, same image)
   + `COPY lineage` in the dockerfile. Bring up the full stack + verify: `scripts/governance_e2e.sh`.
9. ⛔ **Routes-vs-spec conformance test** — FastAPI routes ⊆ lance-namespace spec ops.
10. ⛔ **Lineage version linkage** — record the Lance dataset **version** each run event maps to,
    so provenance and time-travel line up.

### P1 — verified security/consistency cleanups (audit `w8u4rc2tg`)
- ⛔ **OpenFGA tuple cleanup on drop / deregister / rename** — `app/core/fga.py` is **write-only**
  (`write_tuples` issues `ClientWriteRequest(writes=…)`, no deletes); `drop_table`/`deregister_table`/
  `drop_namespace`/`rename_table` leave stale `owner`/`parent` tuples → **stale-grant privilege bleed**
  if an id is reused. Add a `ClientWriteRequest(deletes=…)` path + call on drop/deregister/rename.
  **✔audit**. Touch: `app/core/fga.py`, `app/api/v1/endpoints/tables.py`, `namespaces.py`.
- ⛔ **Wire or remove unused `can_list` / `can_alter` / `can_commit` / `can_rename`** — defined in
  `app/auth/model.fga` but `fga_deps.py` never checks them (rename→`can_write_data`, list→`can_get_metadata`).
  Maintenance hazard: the model advertises finer granularity than enforcement implements. **✔audit**.
  Touch: `app/api/fga_deps.py`, `app/auth/model.fga`.

### P2 — later / deferred
11. 🔶 **Lineage events for delete/drop, schema evolution, compaction/maintenance** — complete
    the provenance surface beyond create/append.
12. 🔶 **Read/access audit** in lineage (who *read* what, not only who wrote).
13. 🔶 **Governance P1** — `project` type + 3-axis (teams × projects × layers); versioned
    OpenFGA-model migrations + reconcile-from-catalog (Lakekeeper patterns).
14. 🔶 **Async lineage ingest** (jobs → NATS → consume) · **Dapr** workflows · **OTel** traces/metrics.

---

## Security & consistency backlog (verified — audit `w8u4rc2tg`, 5/9 high-criticals confirmed)
Severity in brackets; "latent" = real but not live today (lineage svc undeployed).
- ✅ **[high]** Lineage **read** endpoints unauthenticated → data-estate disclosure. **FIXED** —
  OIDC + `can_get_metadata` gate + `batch_check` transitive-disclosure filter (`lineage/auth.py`). → **P0 #1**.
- ✅ **[high→latent]** Lineage **ingest** unauthenticated + `author` **self-asserted** → forgeable
  audit graph. **FIXED** — ingest requires a verified token; `enforce_author` binds `author`=`token.sub`
  (`lineage/auth.py`, `lineage/main.py`). → **P0 #2**. *(Remaining: optional output-scoped ingest authz.)*
- **[high]** Catalog emits **no lineage** on any write → no audit record of **who created/changed a table**
  (`grep app/` = 0). → **P0 #3**.
- **[low→latent]** Lineage hardcodes `$` while catalog delimiter is configurable → cross-axis identity
  mismatch (`config.py:28` vs `lineage/seed.py`). → **P0 #4 / P1 cleanup**.
- **[high consistency]** HCP "static per-bucket keys from OpenBao" is **false** — HCP keys are tenant-wide
  `md5(password)` identity keys, unrotatable, non-expiring (`ra-hcp …/auth_utils.py:37-38`). Docs +
  `vending.py` docstring corrected; pin `mode_b`. → folded into **P1 #5**.
- **[low security]** Stale OpenFGA tuples on drop/rename → stale-grant bleed. → **P1 cleanups**.
- **positives (verified):** catalog OpenFGA enforcement is consistently **fail-closed**; lineage openCypher
  is **injection-safe** (agtype bind params). *(Refuted/false-positive: 4/9 — adversarial filter working.)*

---

## Security checklist (apply throughout)
- Secrets in **OpenBao**, never env/files; rotate; least-privilege catalog credential.
- **Compute jobs use workload identity, never stored storage keys** — creds are vended, short-TTL, scoped.
- TLS client↔catalog and catalog↔storage; OIDC short-lived JWTs + JWKS rotation.
- **Fail-closed** authz; **audit every authz decision + data access** (lineage is the audit graph —
  so it must itself be authenticated, authorized, and forgery-proof).
- **Lineage read AND ingest authz-gated**; **provenance author verified** (no client-claimed author).
- Network: catalog + lineage in a private subnet; object storage never public.
