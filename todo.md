# Lance REST Catalog — Roadmap / TODO

**Legend:** ✅ done · 🟡 in progress · ⛔ not started · 🔶 deferred
**Priority:** `P0` security/correctness blocker · `P1` needed for prod · `P2` later

> Reconciled with the grounded audit **`w8u4rc2tg`** (4 read-only auditors → adversarial
> verification → synthesis; **5/9 high-criticals confirmed**, all `file:line`-cited). Items tagged
> **✔audit** are verified against the real code. Caveat: the lineage authz items are real but
> currently **latent** — the lineage service is undeployed/unreachable today, so they are
> **P0-on-deploy** rather than live prod exposure.

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
1. ⛔ **Lineage READ authz** — gate `upstream/downstream/producers/graph` with OIDC +
   OpenFGA `can_get_metadata` on `table:<id>`. Reuse `app/core/oidc.py` + `app/core/fga.py`.
   *Today these are unauthenticated → they leak the entire data estate.* **✔scan** `lineage/main.py`.
2. ⛔ **Lineage INGEST authz + verified author (anti-forgery)** — the ingest endpoint is
   unauthenticated and the author is **self-asserted** (`lineage/seed.py:79` → `lineage/models.py:52`),
   so anyone can POST forged provenance and poison the audit graph. Require a service identity
   on ingest **and** set `author` = the authenticated principal (reject/override client-claimed
   author). **✔scan** `lineage/main.py`, `lineage/models.py`.
3. ⛔ **Catalog emits lineage on create / insert / delete** with `author` = authenticated `token.sub` —
   *this is how "who created the table" actually gets logged authoritatively* (the catalog is the
   only component that knows the verified principal on every write). Catalog currently emits
   **nothing** to lineage. Add a first-class `(:User)-[:CREATED]->(:Dataset)` edge + the resulting
   Lance `version` on the Dataset; wire emission **fire-and-forget** (async/NATS) so it never blocks
   the commit. **✔audit** (no `emit`/`openlineage` anywhere in `app/`). Touch: `app/api/v1/endpoints/data.py`,
   `tables.py`, `namespaces.py` (emit); `lineage/repository.py`, `models.py` (CREATED edge + version).
4. ⛔ **Identity-consistency guard + test** — assert `table:<id>` is byte-identical across the
   OpenFGA object id, the catalog table id, and the AGE `Dataset` node name. The catalog delimiter is
   **configurable** (`LANCE_NS_DELIMITER`, `config.py:28`) but lineage **hardcodes `$`** (`lineage/seed.py`)
   → silent cross-axis mismatch under a non-default delimiter. **✔audit** (latent). Touch:
   `app/core/identifiers.py`, `app/core/fga.py`, `lineage/config.py` (+ derive names from `canonical_object_id`).

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
8. ⛔ **Deploy lineage** — `lineage-api` compose service + `COPY lineage` in the image.
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
- **[high]** Lineage **read** endpoints (`upstream/downstream/producers/graph`) unauthenticated →
  data-estate disclosure (`lineage/main.py:63-85`). → **P0 #1**.
- **[high→latent]** Lineage **ingest** unauthenticated + `author` **self-asserted** (`lineage/main.py:51-60`,
  `models.py:51-57`) → forgeable audit graph; `producers()` returns the spoofable author verbatim. → **P0 #2**.
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
