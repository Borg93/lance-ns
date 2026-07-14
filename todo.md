> **⚠ SUPERSEDED for current priorities (2026-07-14): the single source of truth for WHAT WE DO NOW is [`docs/GOAL-prove-it.md`](docs/GOAL-prove-it.md). This file is kept as historical planning context only.**

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
>
> **Update:** P0 #3 (catalog create-lineage) + lineage deploy + governance demo/e2e shipped &
> reviewed (audit `w1f441qze`, ship-with-nits). Nits fixed: emitter **forwards the caller's bearer**
> (so prod lineage-OIDC accepts create events), real `version` from the response, **deterministic
> `creator()`** (latest-create-wins), suppressed shutdown closes, lineage-api healthcheck/hardening,
> `EXPOSE 8000`, and a docs/diagram staleness sweep.

---

## Done (built + tested)
- ✅ **GOAL 4 — lineage discovery + a truly event-driven cascade** (lance-ns only):
  - **A1/A2** governed `GET /datasets` (`?namespace=`/`?tag=` + pagination), `/jobs`, `/namespaces` — the
    graph is now browsable, not just walkable (unit + AGE-backed integration tests).
  - **A3** frontend **Browse** landing backed by `/datasets` (replaces the hardcoded name list); Playwright.
  - **B1** `medallion.compute` toggle → the cascade writes real Lance data (requires OpenBao off; fail-fast
    boot guard otherwise). **B3** `medallion.quality` toggle wires the validator gate into the chart.
  - **B2** event-driven cascade **head**: lance-ray subscribes (`/raw-arrival`) and fires `medallion.raw`
    from the raw-write event — no manual trigger, no cron (verified live: +4 runs per produce).
  - **B4** storage→graph reconciliation **back-fill** (repository + `reconcile_all` + a Dapr-cron route) for
    writes whose lineage event was lost — the buildable half of the outbox problem (AGE-backed test).
  - Deferred to the query-engine/rask phase: semantic `/search`, DuckDB SQL, MVs, control-plane API.
- ✅ Lance Namespace REST catalog — FastAPI over native pylance `DirectoryNamespace` (MinIO/S3).
- ✅ OIDC authn (PyJWT/JWKS), **fail-closed**.
- ✅ OpenFGA authz — op→`can_*` actions, concentric owner⊇writer⊇reader, parent cascade
  (`catalog→namespace→table`), roles as `role:#assignee`, `catalog:lance` root,
  `grant_on_create`/`seed_ownership`. Model at `services/common/auth/model.fga` (+ `.fga.yaml` tests).
- ✅ Resilience — transient-aware retries; network errors → 503 (never escape as 500).
- ✅ Postgres (OpenFGA datastore) over sqlite.
- ✅ Auth e2e + docker compose overlays; `docs/ARCHITECTURE.md`.
- ✅ Pluggable `CredentialVendor` scaffold — `services/catalog/core/vending.py` (ModeB / StaticPrefix / Sts).
- ✅ Read-only maintenance middleware — `services/catalog/api/maintenance.py` (default OFF).
- ✅ Lineage service (incoming) — `services/lineage/`: OpenLineage ingest → Apache AGE graph,
  `upstream/downstream/producers/graph`; dataset name = catalog `table:<id>`; injection-safe
  Cypher (agtype bind params). **Open holes below.**
- ✅ Interactive system diagram — `docs/system-diagram.html` + `docs/system-diagram.md`.
- ✅ **Lineage auth (P0 #1/#2)** — in-service OIDC + OpenFGA `can_get_metadata` gate on all reads
  (+ `batch_check` transitive-disclosure filtering via `DatasetFilter`) and ingest authn +
  verified-author binding; reuses the catalog's verifier/check. Default OFF, fail-closed.
  `services/lineage/api/{security,fga_deps}.py`, `services/lineage/core/config.py`, `services/lineage/main.py` (reviewed by audit `wi2l437mq`).
- ✅ **Structured logging standardized** repo-wide (event-name + `extra=`, level discipline per
  `observability.md`) + authz-decision audit logging (`access_denied`) in catalog + lineage.
- ✅ **Catalog → lineage emission (P0 #3)** — table create emits OpenLineage with the verified author
  → `(:User)-[:CREATED]->(:Dataset)` + `GET /datasets/{id}/creator`. Default OFF, fire-and-forget.
- ✅ **Lineage service deployed** (`lineage-api`, P1 #8) + **governance demo/e2e** — `scripts/governance_demo.py`
  (narrated) + `tests/e2e/test_governance_e2e.py` (gated) + `scripts/governance_e2e.sh` over the full stack.
- ✅ **HCP dropped → S3-compatible only** (MinIO default; AWS / Ceph RGW / RustFS / GCS-interop). Code +
  docs + diagram reframed to **Mode B (server-mediated) vs STS vending**. RustFS storage-agnostic e2e:
  `.docker/docker-compose.rustfs.yml` + `scripts/rustfs_e2e.sh` (same lifecycle test, bytes on RustFS).
- ✅ **Realistic medallion lineage sim + version linkage (P1 #10)** — `services/lineage/seed.py`: alice ingests
  bronze → data_eng embeds silver (v1, +`embedding`) → refines silver in place (v2, +`caption`) →
  analyst aggregates gold; each output carries its Lance `version`. `producers()` surfaces the version;
  in-place refine bumps version (no self-loop). Unit-tested; `test_lineage_e2e.py` asserts the chain + v1/v2.
- ✅ **OpenLineage standards fidelity (P1 #10b)** — emit only via official `openlineage-python` facet
  classes (Marquez-ingestible). Capture the standard facets: `producer`, `ownership` (author fallback),
  `jobType` (Ray compute, BATCH, ETL into bronze / TRANSFORMATION between layers), `dataSource`
  (→ node `source_uri`), `tags` (→ node `tags`), `errorMessage`. **Failed runs recorded** (FAIL/ABORT
  → run + error + `WROTE` with no version, **no** `DERIVED_FROM`/`CREATED` — no fabricated lineage);
  seed includes a failed embed. Gold **embeds its lineage as a JSONB column** in the Lance file
  (`pa.json_()`). Unit + e2e updated. Ray=compute / Lance=data documented in `docs/LINEAGE.md`.

---

## Decisions locked
- **Secret manager:** OpenBao (Vault-API / KV-v2 compatible).
- **Object store = S3-compatible** (MinIO is the default test backend; AWS S3, Ceph RGW, RustFS,
  GCS-via-interop). HCP was dropped — no non-standard backends.
- **OpenDAL: evaluated and REJECTED (2026-07-10)** — interoperability lives at the PROTOCOL layer
  (S3-compatible-only, above) + the standard surfaces (Namespace REST / OpenLineage / OpenFGA), not in a
  unified client library: the hot path is pylance's internal `object_store` (not ours to swap), the CAS
  gate validates THAT layer specifically, and a third S3 client stack would multiply signing/addressing
  drift. Revisit triggers: a hard non-S3 backend requirement, or upstream Lance adopting OpenDAL.
- **Data plane = vending-first, pluggable `CredentialVendor`:**
  - **`StsVendor`** (short-TTL, per-table-scoped `AssumeRole`) — the **recommended path**; works on
    any STS-capable S3 (MinIO, Ceph RGW, AWS).
  - **`ModeBVendor`** (server-mediated; no credential leaves the catalog) — the simple,
    backend-agnostic default (nothing delegated).
  - **`StaticPrefixVendor`** (static per-bucket key from OpenBao) — for S3 backends without STS
    (e.g. GCS interop).
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
- **Postgres is state-of-record ONLY** — the **AGE lineage graph** + the **OpenFGA store**. The
  **catalog is pure Lance/S3** (no DB dependency). **No relational/Postgres task queue** — all async /
  queued / scheduled / event work runs on **NATS JetStream + Dapr** (Jobs / Workflow / pub-sub).
  (Lakekeeper uses a Postgres task queue; we deliberately do not.)

## Contribution boundary → rask (2026-06-30)
This project's deliverable is **merged into the sibling `rask/` repo**, not shipped standalone. That fixes
the scope hard. **The concrete migration plan is [`docs/RASK-INTEGRATION.md`](RASK-INTEGRATION.md)** — chart
fold-in, the externalization → operators mapping, the lance-ray seam contract, and what to drop.
- **What we bring to rask:** the **lakehouse** (the Lance REST catalog + the in-process dataplane), **Dapr**,
  and the **event-driven estate** (the medallion raw→bronze→silver→gold cascade, the lineage service →
  AGE graph, the compaction/GC cron). This is the unit that must be clean + mergeable.
- **What rask already provides (use, don't rebuild here):** the **frontends** (SvelteKit microfrontends)
  and the **operators** — **CloudNativePG** (Postgres), **rustfs-operator** (S3), **KubeRay + Kueue** (Ray).
  → lance-ns's own `frontend/` and the hand-rolled chart infra (AGE StatefulSet, RustFS Deployment) are
  **demo scaffolding** here, superseded by rask. Don't reinvent CNPG/rustfs-operator.
- **Deployment model = ephemeral, spin-up-per-workload** (like rask): the whole platform stands up + tears
  down with the cluster. **Persistence lives in the DATA, not the server** — the pre-ingest S3 input and the
  **gold dataset (which embeds lineage as JSONB)** are exported to permanent storage, with **stage-level
  recovery via Lance version time-travel**. The catalog/lineage processes are stateless + disposable.
- **✅ App-tier HA (P3, DONE 2026-06-30):** the stateless request-serving services (catalog/lineage/gateway/
  web) + movers take configurable `replicas` + a gated `PodDisruptionBudget` + optional CPU `HPA`
  (`chart/templates/ha.yaml`; prod overlay → 2 replicas + PDB on). This is plain Deployment config, NOT
  operator territory. Compaction stays a singleton (its cron must not double-run); producer stays 1.
- **✅ Backups (P4, DONE 2026-06-30):** gated, OFF-by-default backup CronJobs for the SELF-CONTAINED
  in-cluster path — `pg_dump` (lineage + OpenFGA → the lakehouse S3) + a CSI `VolumeSnapshot` of the RustFS
  PVC (`chart/templates/backup-{pg,snapshot}.yaml`; prod overlay turns them on; creds via secretKeyRef). When
  you externalize to **CloudNativePG / rustfs-operator** (the rask path), DISABLE these — the operators do
  PITR/scheduled backups better; the chart documents this. A fallback for the no-operator deploy, NOT a
  reinvention.
- **🔶 STATEFUL HA → rask:** Postgres/RustFS failover/replication is CNPG/rustfs-operator's job in rask (the
  P1 externalization hooks point the apps at the operator-managed store).
- **⛔ Confirmed OUT of scope (N/A for spin-up-per-workload, reinforcing the Lakekeeper-reference stance):**
  multi-warehouse data plane, control-plane management REST API, soft-delete/undrop. Isolation = a separate
  cluster per warehouse; provisioning = Helm (declarative); the catalog serves ONE fixed root.
- **Mergeability bar:** the lakehouse + Dapr core must stay **low-coupled** — services talk only over
  Dapr/NATS + HTTP, never a shared DB or each other's code; `common` is a flat shared lib. This (not infra)
  is the priority to validate before contributing.

### Shipped this session (2026-07-13) — the full KIND-RUNBOOK live pass + 3 features
The pass DROVE every 🟡 "code-complete, live-pending" item on the real kind union stack and found **8
live-only bugs CI structurally can't catch** (fresh-cluster unit + chart-render). Full record: todo_fable
§7a, verification matrix: todo_confirm. Both e2e suites green; 486 unit; ruff/ty clean.
- ✅ **8 live-only bugs fixed + re-proven**: web image never booted (bun workspace); durable-consumer
  config-drift kills all delivery ~25 min on a config-changing upgrade (reconcile added); 🔒 the trainer
  FGA gate was DEAD (revoked trainer still trained); `TOKEN` env collided with Lance's AWS-session-token
  fallback → training 100% broken (→ `TRAIN_TOKEN`); `MEDALLION_RAY_ENABLED` never reached the producer
  (/train 409'd); 🔒 the ServiceAccount flip CrashLooped every Dapr pod (built-in k8s secret store);
  🔒 RustFS was write-dead under the security flip (uid 1000 vs image/data 10001 — reads passed, writes
  500'd); input version pins emitted-then-dropped at ingest (280 READ edges, 0 versions). The recurring
  shape: a flag wired in one place but not another, or a check that only tested the easy direction.
- ✅ **Trainer lineage credential (governed)** — the Ray train job authenticates to the HTTP ingest as
  `service-trainer` (a `ServicePrincipal`: app token + bare FGA subject, NOT a Dex user), is stamped as
  author, and is FGA-checked on outputs. Under auth ALL training provenance was silently 401'd before;
  now it lands. e2e-guarded (governed-union test 5). See docs/RAY-TRAIN.md D2.
- ✅ **`GET /runs/{id}/inputs`** — surfaces a run's PINNED input versions (the READ-edge version, #115 D1's
  reproducibility claim), governed. Was Cypher-only. Answers "which feature versions made this model".
- ✅ **Media stages run on Ray (Phase 3 multimodal)** — verified LIVE that lance-ray 0.4.2 `read_lance`
  strips blob-v2 typing (`extension<lance.blob.v2>` → `large_binary`), so `ray_stage_job.py` gained a
  pylance blob round-trip + inline derive (drift-pinned to services), the ray image ships Pillow, and the
  in-process fallback gate is GONE. `/ingest-media` (ray on) now runs the media stage AS a Ray job with
  blob-v2 preserved + thumbnail/embedding. **This advances P1 #6's media half** — the mover→Ray-job seam is
  done; the KubeRay-operator swap is the remaining rask-merge step. Exit note (docs/RAY.md): a lance-ray
  bump that preserves inline blob typing lets us drop the round-trip.
- ✅ **PSA sidecar hardening** — gated `dapr.sidecarRestricted` flag (render-asserted); full `restricted`
  enforce parked-by-design (Vector's hostPath structurally blocks single-namespace enforce). See §6.4.

### Shipped this session (2026-07-10)
- ✅ **§7a governed-union audit follow-ups** (4 majors + smalls; the s3:// positive control RESOLVED AS
  IMPOSSIBLE — OpenFGA object ids hold exactly one `:`) and **compaction failure visibility** (FAIL
  RunEvent per maintain:-errored dataset, deterministic flood-guard run id, `defer_index_remap`) — both
  adversarially reviewed; live re-runs consolidated in todo_fable §7a RESIDUAL.
- ✅ **Ray TRAIN vs Ray DATA design DECIDED** — `docs/RAY-TRAIN.md`: separate `/train` head + own topic,
  submit-and-ack trainer, jobType=TRAINING lineage with per-feature version pins, **model registry = a
  Lance dataset pointing at plain-path S3 artifacts** (bytes-then-commit = atomic registration; MLflow
  optional in three documented shapes). Implementation #115a–c ALL code-complete (2026-07-10/11,
  adversarially reviewed at the unit tier — incl. the training job, the D4 registry publish, and a
  `TRAINING` JetStream stream the deployed bus was missing); live kind drive + chart values
  passthrough remain, consolidated in todo_fable §7a RESIDUAL.
- ✅ **§4 reliability pair**: `/merge_insert` now ensures a BTREE on its merge key (list-first, idempotent,
  best-effort, `use_index=false` opt-out) and `create_table` COMPENSATES a failed owner grant
  (revoke + drop, fresh-id only — never ExistOk-kept or Overwrite-replaced tables).
- ✅ **lance_docs currency audit + refresh** (upstream content-diffed; namespace was current, guide/format
  refreshed; spec.yaml → 0.9.0, still 54 ops) → **describe-at-tag FIXED** (native silently ignores `tag`;
  the catalog resolves it — also fixed the pre-existing /tags/version 500 on unknown tags).
- ✅ **Lance-native IO metrics pre-wired** (`common/lance_metrics.py` in all five Lance-I/O lifespans;
  pylance 8.0.0 is the NEWEST PyPI release — activation is the future `pylance[otel]` 9.0 bump).
- 📌 Decision pins: OpenDAL evaluated-and-rejected (protocol-level interop via S3-compatible-only +
  the standard REST/OpenLineage/OpenFGA surfaces; revisit on a hard non-S3 requirement or upstream Lance
  adoption); AutoCleanupConfig available but NOT adopted (sweep stays the one GC owner).

### Shipped this session (2026-06-30)
- ✅ Security/durability/authz hardening: RustFS PVC durability, external-endpoint hooks (P1),
  external-secrets operator + secrets-via-Dapr decouple (P2), and the **stale-FGA-tuple revoke** on
  drop/deregister/drop_namespace/rename (closes the privilege-bleed; was P1 `w8u4rc2tg`). All adversarially
  audited + tested.
- ✅ **In-repo lineage backlog close-out** (commits `163f459`/`d618d19`/`7880dfe`/`4b2adb1`):
  **durability fix** — all catalog write-emits converted from FastAPI `BackgroundTasks` (no retry, dies with
  the worker — the anti-pattern) to **inline-awaited** publishes on the durable Dapr/JetStream transport;
  **#2** output-scoped ingest authz (`can_write_data` on every claimed output); **#4** dropped unused FGA
  relations; **#5** `/events` retention; **#6** read-audit log; **#7a** drop-table lineage; **#7b**
  compaction maintenance lineage. Every item has valuable unit tests; full suite + ruff + ty green.

#### Track F (spec-completeness) — REVISED 2026-06-30 (my earlier "upstream-blocked" verdict was wrong)
After reading the Lance Namespace spec docs (`lance-namespace/docs`) + an adversarial audit, the earlier
"not buildable / upstream pylance limits" verdict was **materially wrong**. Corrected:
- **F2 (version management)** — ✅ **DONE / was never really blocked.** `describe` / `create` /
  `batch-delete` table versions were **fake 501s from a marshalling bug** (the 3 native bindings are typed
  `request: dict` and forward to Rust without `model_dump()`; the pydantic `TypeError` got laundered into a
  501 by a too-broad stub hint). `native.call` now marshals to dict → all three 200, `describe` carries
  `manifest_path`, missing version → 404. **Branches** (a real native 501) are backed via the dataplane
  (`ds.branches` / `ds.create_branch`), like tags. 6 ops moved 501→200; see `docs/COVERAGE.md`. (Remaining
  version 501s: `batch-create` / `batch-commit` — external-manifest-store batch ops the dir backend doesn't
  implement; a REST backend would.)
- **F1 (MV `base_objects` view-dependency index)** — 🔶 native-backend-stubbed, real MV is greenfield. My
  "pylance has NO MV API" was wrong: pylance ships the *complete* typed MV API + delegation; the native
  **dir backend** raises `NotImplementedError` → 501. A real MV is a query-materialization subsystem (query
  engine → write Lance table → incremental refresh) — buildable but a new subsystem, out of scope here.
- **F3 (Partitioned Namespace family)** — ❌ DROPPED BY DESIGN. Correction: the spec **does** ship the
  primitives (`PartitionSpec` / `PartitionField` / `PartitionTransform` — full Iceberg transform set), but
  they're **defined-but-unwired** (no `partition_spec` on `CreateTableRequest`) AND the Lance **data format**
  deliberately doesn't directory-partition — it skips via **fragments + zone maps + columnar layout +
  secondary indices**, a better design for our workloads. We **reject** Iceberg-style partitioning (thesis-
  aligned, like multi-warehouse / soft-delete), not "no primitive exists".
- ✅ **Core validation** (validation `wfefr8vtx`, 6 agents, live probe → adversarial verify; see
  `docs/COVERAGE.md`). Verdict: the lakehouse + event-driven core is **valid, low-coupled, and mergeable**
  (zero cross-service imports; fail-closed authz; official OpenLineage idempotent MERGE; resilient cascade).
  Catalog = **41/54 ops backed (200), 13 spec-correct 501s** (native pylance backend limits: rename,
  backfill, version-mutation, branches, MV, alter_transaction — not catalog gaps). Stage recovery
  (`restore_table`) + `/reconcile` validated. The "compaction wipes gold" alarm was **refuted** (current
  version always kept; only >7d time-travel history GC'd).
  - **The one in-scope gap (by design = the rask seam):** the movers emit **provenance by default**, and
    **real Lance data when `MEDALLION_COMPUTE_ENABLED`** (the in-process fake-Ray compute). What's left is
    the **distributed** producer — **lance-ray** (Ray Data job on rask's KubeRay, P1 #6) — plus the gold
    whole-history JSONB embed in the deployed path (today only in `medallion_demo.py`).
  - Minor partials (noted, not blockers): compaction time-travel retention is global 7d not per-stage;
    `can_alter`/`can_commit`/`can_rename` modeled-but-unwired; routes-vs-spec conformance test (P1 #9) absent.

---

## Next (priority order)

### P0 — security / correctness (do first)
1. ✅ **Lineage READ authz** — `upstream/downstream/producers/graph` gated on OIDC +
   OpenFGA `can_get_metadata` on `table:<name>`, reusing the catalog's `OIDCVerifier` +
   `fga.check` (`services/lineage/api/{security,fga_deps}.py`, `services/lineage/main.py`). Default OFF, fail-closed when enabled.
   **Plus** transitive-disclosure filtering: related/graph datasets the caller can't see are
   dropped via `fga.batch_check` (`DatasetFilter`), mirroring the catalog's `list_objects`
   filtering. *(audit `w8u4rc2tg` follow-up; reviewed by `wi2l437mq`.)* **Prod must set
   `LINEAGE_OIDC_ENABLED` + `LINEAGE_FGA_ENABLED`.**
2. ✅ **Lineage INGEST authz + verified author (anti-forgery)** — ingest requires a verified
   token (401 otherwise) and `enforce_author` binds `author` = `token.sub`, overwriting any
   body-claimed facet (`services/lineage/api/{security,fga_deps}.py`, `services/lineage/main.py`). Tested end-to-end so deleting the
   bind regresses a test. **Output-scoped authz DONE (2026-06-30)**: `enforce_output_authz` now requires
   `can_write_data` on every claimed output (a producer can't record provenance for a table it can't write).
3. ✅ **Catalog emits lineage on create** with `author` = the verified `token.sub` — "who created
   the table" is now an audit fact: a `(:User)-[:CREATED]->(:Dataset)` edge, queryable at
   `GET /datasets/{id}/creator`. Fire-and-forget + best-effort (never blocks/fails a write), default
   OFF (`LANCE_LINEAGE_EMIT_ENABLED`), canonical id (lineage Dataset == OpenFGA object id).
   `services/catalog/core/lineage_emit.py`, `services/catalog/api/v1/endpoints/data.py`, `services/lineage/models.py`, `services/lineage/services/repository.py`, `services/lineage/main.py`.
   *(Remaining → P2: emit on insert/merge/delete/compaction + Lance-version linkage.)*
4. ✅ **Identity-consistency** (DONE 2026-06-30) — the catalog emits lineage via `fga.canonical_object_id`,
   so a catalog-created Dataset name == its OpenFGA object id == the embedded Lance metadata id under any
   delimiter. **Locked** by `tests/unit/test_cross_axis_identity.py`: the `parse_identifier`∘`canonical_object_id`
   round-trip across 4 delimiters (incl. non-default `.`/`/`/`::`), plus a handler-level test driving the real
   `create_table` under a `.`-delimited config that asserts all three axes (FGA grant object / lineage Dataset /
   embedded metadata id) byte-identical. (`services/lineage/seed.py`'s hardcoded `$` is demo-only — fixed demo
   dataset names, not a production path.)

### P1 — needed for prod
5. ✅ **Credential vendor — DONE.** Shipped as `POST /v1/table/{id}/credentials` (OpenFGA-tiered:
   `can_read_data`→read, `can_write_data`→write; default `mode_b`). Vendors: `StsVendor` (AssumeRole +
   per-table session policy), `WebIdentityVendor` (AssumeRoleWithWebIdentity — the RustFS-native path,
   exchanges the caller's OIDC token), `StaticPrefixVendor`, `ModeBVendor`.
   `services/catalog/core/vending.py`, `services/catalog/api/v1/endpoints/credentials.py`. (Adversarially
   audited; bearer-seam / 4xx-mapping / client-caching fixes applied.)
6. ⛔ **DISTRIBUTED lance-ray promotion + compaction** (bronze→silver→gold) on the KubeRay cluster — the REAL
   Ray Data jobs (`lr.read_lance`/`write_lance`, `lr.compact_database`) that write the stages + emit
   OpenLineage at scale. (The movers/compaction already do the same read→transform→write→version contract
   **in-process** via the opt-in fake-Ray compute; the gap is the *distributed* layer.) **It lands in the
   rask merge** — see
   `docs/RASK-INTEGRATION.md` (the lance-ray seam contract). The event-driven cascade + the gold JSONB-lineage
   demo already prove the seam the real job drops into.
7. ✅ **OpenBao SecretStore — DONE (two-tier model).** App tier (catalog/lineage/compaction) consumes
   secrets from OpenBao via the Dapr secret store as the STRICT sole source (fail-closed, no env fallback);
   infra tier (AGE/RustFS servers, OpenFGA migrate) via `secretKeyRef`. The external-secrets operator syncs
   the infra Secret from Vault (P2); `secretsViaDapr` keeps apps on Dapr even with an external Vault.
   lance-ray = workload identity (no Bao). Invariant: 0 plaintext secrets in any prod-render workload.
8. ✅ **Deploy lineage** — `lineage-api` service (`.docker/docker-compose.governance.yml`, same image)
   + `COPY lineage` in the dockerfile. Bring up the full stack + verify: `scripts/governance_e2e.sh`.
9. ✅ **Routes-vs-spec conformance test** (DONE 2026-06-30) — `tests/integration/test_spec_conformance.py`
   asserts every one of the 54 spec operations has a served route (via `app.openapi()`, since starlette's
   lazy `include_router` hides routes from `app.routes`). 0 missing. Locks the faithful-REST-surface property.
10. ✅ **Lineage version linkage** — the `WROTE` edge carries the Lance **version** each run
    produced (OpenLineage `version` facet → `producers().dataset_version`), so refinement passes
    (silver v1 → v2) are distinguishable and provenance lines up with time-travel. In-place refines
    bump the version instead of creating a self-`DERIVED_FROM` edge. `services/lineage/models.py`, `services/lineage/services/repository.py`.
11. ⛔ **OpenBao off dev-mode + a secrets operator** (`docs/OPERATORS.md` §5, row 5). **Live incident
    2026-07-14:** `server -dev` keeps secrets **in memory**, so an out-of-band OpenBao restart wipes
    `secret/lance`; the `openbao-seed` re-seed is a *post-upgrade hook*, so a bare restart never
    repopulates it → every app's `apply_dapr_secrets` retries a Dapr `500` forever → lifespan hangs,
    pod stuck `0/2`, daprd deadlocked waiting for the app to bind. Two levels:
    - **(a) Interim — a values flip, do soon (P1):** `openbao.devMode=false` → `server -config` on the
      existing PVC so secrets survive restarts. Adds a one-time `operator init`/unseal (no fixed root
      token) — the very chore the operator removes, so this is the bridge.
    - **(b) Operator — the destination (P2, operator wave):** External Secrets Operator (lowest coupling,
      cloud-agnostic) / Vault-OpenBao operator / bank-vaults for **auto-unseal** + **declarative secret
      sync** (retire the seed Job) + rotation. First check whether rask already operates one (it operates
      the other four operators) — if so the merge is a values flip, not an install.

### P1 — verified security/consistency cleanups (audit `w8u4rc2tg`)
- ✅ **OpenFGA tuple cleanup on drop / deregister / rename** (DONE 2026-06-30) — added the revoke path to
  `services/common/fga.py` (`read_object_tuples` paginated + `delete_tuples` per-tuple/idempotent +
  `revoke_object_tuples`) + `fga_deps.revoke_ownership`, wired into `drop_table`/`deregister_table`/
  `drop_namespace` and `rename_table` (revokes the SOURCE id, seeds the dest). Closes the stale-grant bleed.
  Adversarially audited (12/12 findings addressed — incl. the OpenFGA transactional-delete masking fix +
  endpoint wiring tests). `services/common/fga.py`, `services/catalog/api/v1/endpoints/{tables,namespaces}.py`.
- ✅ **Removed unused `can_list` / `can_alter` / `can_commit` / `can_rename`** (DONE 2026-06-30) — the model
  advertised finer granularity than enforcement implemented (rename→`can_write_data`, list→`can_get_metadata`).
  Dropped from all 3 synced model files (`model.fga` / `.fga.yaml` / `.json`, regenerated via the fga CLI
  transform); `fga model test` green. Closes the maintenance hazard.

### P2 — later / deferred
11. ✅ **Lineage events for delete/drop + compaction/maintenance** (DONE 2026-06-30) — the provenance surface
    now extends beyond create/append: `drop_table` emits a versionless drop run (#7a, the Dataset node
    persists as history) and the **compaction service emits a versionless `operation=compaction` maintenance
    run per materially-compacted dataset** (#7b, `services/compaction/core/lineage_emit.py` → Dapr pub/sub,
    off by default). Both awaited inline on the durable transport (not FastAPI BackgroundTasks). (Insert/
    merge/update/delete already covered by #19.) *(Remaining sub-surface: schema-evolution-only events.)*
12. ✅ **Read/access audit** (DONE 2026-06-30) — `audit_read` logs WHO read which dataset to
    `public.lineage_reads` on every gated per-dataset read (datasets/columns/reconcile routers), AFTER the
    authz gate. Off by default (`LINEAGE_READ_AUDIT_ENABLED`); best-effort (never fails a read).
    `services/lineage/api/fga_deps.py`, `services/lineage/services/repository.py`.
12b. ✅ **Column-level lineage** (DONE 2026-06-30, backend + UI) — backend #24 (`(:Column)-[:DERIVED_FROM_COLUMN]->`
    graph + gated/governed `/columns` queries, 2 live e2e) **and the Svelte Flow field-to-field UI**:
    `frontend/src/lib/ColumnNode.svelte` (layer palette, masking shield, Arrow type) + a **Columns** graph-view
    tab in `+page.svelte` (`loadColumns()` → `/datasets/{name}/columns`, live 2s poll, red-dashed masking
    edges, empty-state guidance). `bun run check` clean (4549 files, 0 errors). Migrates to rask's
    microfrontends later as a portable component. *(Fast-follow: schema-diffing between Lance versions.)*
13. 🔶 **Governance P1** — `project` type + 3-axis (teams × projects × layers); versioned
    OpenFGA-model migrations + reconcile-from-catalog (Lakekeeper patterns).
14. 🔶 **Async lineage ingest** (jobs → NATS → consume). *(The old "OTel traces/metrics" third of this line
    SHIPPED: OTLP-direct → GreptimeDB + Vector + Perses, `make e2e-obs` — see todo_confirm §11; Lance-NATIVE
    IO metrics are pre-wired and activate at the pylance 9 bump.)* **⛔ The "· Dapr workflows" clause is
    RETIRED (2026-07-12 rule, reaffirmed 2026-07-13):** the cascade stays **choreography** (each hop reacts
    to its trigger + publishes the next), and the gold QC gate is a **mover-side quality check**, not a
    Dapr Workflow — Dapr Workflow is reserved for a genuinely non-idempotent multi-step orchestration, and
    none exists in this system (every hop is idempotent on a deterministic run-id). Docs that still show a
    "Dapr-Workflow QC gate" (image-pipeline-event-driven.md) are ASPIRATIONAL-design records with a
    built-differs caveat, not the built system.
15. ✅ **Live medallion demo + SvelteKit UI** — `scripts/medallion_demo.py` *executes* the flow against
    the real stack (RustFS + lineage/AGE): writes bronze (blob `payload`), adds `embedding` then
    `caption` to silver (Lance write + add-column → v1, v2), aggregates gold with the embedded
    `lineage` JSONB — each step emitting **real** OpenLineage. `--step N` lets you be the producer.
    UI = a **SvelteKit app** (`frontend/`, Svelte Flow + bits-ui on Bun) with three live views: Graph (DAG,
    version chips, failed run, source_uri+tags), Events (Marquez-style `/events` with full facets),
    Storage (`/demo/datasets` — real Lance schema per version + gold JSONB). Backend gained `/events`
    + `/demo/datasets` (reads real Lance on S3). `scripts/medallion_demo.sh` brings the whole stack up
    (RustFS + lineage + web; host ports overridable). Zero-dep fallback UI at `/ui/`. *Follow-ups:
    SSE/websocket push instead of polling; route the demo through the catalog control plane.*
16. 🔶 **Demo → production auth/authz (it runs auth-OFF on purpose; here's all that's missing).**
    The enforcement is **already implemented and just flag-gated OFF** (P0 #1/#2/#3 above), so turning
    it on is mostly config:
    - **[config, easy]** Catalog: `LANCE_OIDC_ENABLED`+`LANCE_FGA_ENABLED`. Lineage:
      `LINEAGE_OIDC_ENABLED`+`LINEAGE_FGA_ENABLED` pinned to the **same** `*_FGA_STORE_ID`/`MODEL_ID`.
      Dex + OpenFGA are already in the base compose; just seed the OpenFGA model + tuples.
    - ✅ **UI login flow DONE (2026-06-30)** — the genuinely-new piece, built: OIDC Authorization-Code-+-PKCE
      in the SvelteKit BFF (`$lib/server/oidc{,-core}.ts`, `hooks.server.ts`, `/auth/{login,callback,logout}`,
      httpOnly session) so the `/api/*` proxy forwards a real `Authorization` bearer; lineage then verifies +
      filters. **Opt-in** (`OIDC_ISSUER` unset → demo stays auth-OFF). 15 `bun test` unit tests on the
      security-critical logic (incl. the RFC 7636 PKCE S256 vector); `bun run check` + `vite build` clean.
      End-to-end needs live Dex; session-sealing + refresh are documented prod-hardening fast-follows.
    - ✅ **Demo endpoints hardened (DONE earlier)** — `/events` is persisted (`public.lineage_events`) + gated
      (#22); `/demo/datasets` stays flag-gated (`LINEAGE_DEMO_DATA_ENABLED`, off by default).
    - ✅ **Output-scoped ingest authz DONE (#2)** — `enforce_output_authz` requires `can_write_data` on every
      claimed output, not just authentication.
    - **[data plane] Wire `StsVendor` into `describe_table?vend_credentials`** (P1 #5) — real per-table
      short-TTL creds on MinIO/Ceph/AWS (RustFS: mode_b/static until it supports inline policy scoping).
    Bottom line: **the UI login flow is now built** — turning auth on is config (flip the `*_ENABLED` flags +
    seed the OpenFGA model/tuples + point the UI at Dex via `OIDC_ISSUER`). Only the StsVendor wiring (P1 #5,
    a data-plane nicety) remains optional.
17. 🔶 **Run-status / lifecycle capture (provenance graph ≠ live status).** Lineage used to record only
    terminal `COMPLETE`/`FAIL`, so it couldn't show *progress*, *in-flight failures*, or *where the
    pipeline is now*.
    - ✅ **Driver emits the full OpenLineage lifecycle** — `medallion_demo.py::_emit_step` now sends
      `START → RUNNING (×3, progress 1/3→3/3) → terminal COMPLETE/FAIL`; a failed run dies mid-RUNNING.
      Progress rides a **custom** `ProgressRunFacet{done,total}` (spec has no standard progress facet —
      Marquez shows state+duration, not %), so the provenance graph stays strictly spec-true.
    - ✅ **Durable run-state in AGE** — `GET /runs` → `repository.list_runs()` reads `RunStatus{state,
      progress, outputs, error, timing}` folded **onto the `(:Run)` node in Apache AGE** (not an
      in-memory buffer). **Survives `lineage-api` restart + replica-shared** (verified by restart test):
      ingest SETs `event_type`(=state)/`event_time`(=updated_at, last-wins)/`started_at`(coalesce
      first)/`events_count`/`job` on `(:Run)`, with progress + outputs in their own conditional
      statements. `/events` is the one feed still in-memory (`deque(500)`, ungated) → persist + gate next.
    - ✅ **Live status board in the UI** — `StatusBoard.svelte` (GSAP-animated: width fill, running
      pulse, row entrance) renders each run's state pill + progress bar + error; Svelte Flow nodes get a
      run-state **ring** (running=amber pulse, complete=green, failed=red) via `runStateByDataset`.
    - ⬜ **Real feed (still simulated by the driver).** Production feed = **Ray Event Export** (2.49+,
      alpha): node aggregator POSTs `TASK_LIFECYCLE_EVENT` (RUNNING/FINISHED/FAILED) → map to RunState —
      *no polling*. Caveat: Ray's FINISHED = compute returned, not "Lance committed a version", so join
      Ray-lifecycle (timing) with the job's reported output (version) by jobId; keep the job's
      `*.ready{version}` as the authoritative pipeline trigger. Plus NATS queue depth (pending /
      redelivered / DLQ). See `docs/event-driven-pipeline.{html,md}` (flows 3 "Live status" + 4 "Ray
      Event Export").

---

## Marquez parity → production viability (2026-06-25 session — verified findings)

**Verdict (4-agent adversarial review, source-grounded — workflow `marquez-verdict`):** NOT a Marquez
replacement — a **governance-first** lineage service genuinely ahead on **access control + provenance
integrity *by design***, but behind on **durability, granularity, product surface**, and its
access-control edge **ships OFF by default** (as shipped it's as open as Marquez).

**Real edges Marquez structurally lacks (keep these):** in-service OIDC+OpenFGA read gating; unified
cross-axis identity (`Dataset.name == catalog table:<id> == OpenFGA object == Lance table` via one
`fga.canonical_object_id`); Lance **version on the WROTE edge**; gold's whole-history embedded JSONB;
in-service author-binding (`enforce_author`); failed-run fidelity (no fabricated lineage); single AGE
property graph (one `*1..` Cypher vs Marquez recursive SQL).

**✅ Done this session:** durable `/runs` (lifecycle folded onto the AGE `(:Run)` node, survives restart —
see #17) · gold embeds the WHOLE upstream lineage as JSONB pulled live from the graph (was a hand-typed
stub) · UI: live status board (GSAP) + **Datasets/Jobs view planes** + lucide icons + auto-fit, and fixed
an `effect_update_depth_exceeded` infinite loop (untrack the node-reconcile read) · docs
`image-pipeline-event-driven.{html,md}` (event-driven durable image medallion w/ Dapr QC gate).

### Production-viability checklist (most is "finish the wiring", not hard)
18. ⬜ **Turn auth ON in prod** (`LINEAGE_OIDC_ENABLED` + `LINEAGE_FGA_ENABLED` + store/model ids). The
    capability is wired (5 gated routes, 3-layer fail-closed, 23 unit tests) but DEFAULT OFF → flip it on.
19. ✅ **Real catalog emits the full lifecycle — DONE.** Generalised the emitter to `emit_write` +
    `build_write_event(operation, version: int | None)` (create delegates); wired `insert` / `merge_insert`
    / `update` / `delete` handlers in `data.py` to queue a best-effort write event after the response
    (shared `_queue_write_event` helper). merge/update/delete carry the response's Lance version on the
    `WROTE` edge; insert's response has no version so it records the run + operation without one. Covered
    by unit tests (build/emit for each op + round-trip) + the integration suite (139 tests pass).
    (supersedes P2 #11)
20. ✅ **version-on-WROTE in prod — DONE.** `build_create_event` now attaches the standard
    `DatasetVersionDatasetFacet` (`outputs[].facets.version.datasetVersion`) so a real `create_table`
    persists the Lance version on the `WROTE` edge (was `NULL` — only the demo emitted it). Proven by the
    round-trip unit test (`RunEvent.output_version == "1"`). Revives the storage-version differentiator.
21. ✅ **Lineage ↔ data KEY embedded in the Lance file — DONE (self-describing data).** `create_table`
    now stamps `{lineage.dataset_id, lineage.namespace, lineage.create_run_id, lineage.created_by}` into
    the Lance **schema metadata** (`services/catalog/core/lineage_metadata.py` injects them into the Arrow stream
    before the write; `create_run_id` = the same run id the create event emits, so the file points at its
    creating run in the graph). **Proven in real Lance** by a write→read test (the keys survive
    `write_dataset`). Best-effort (never fails a create); the re-encode runs in the threadpool. The data
    is now reconcilable to the graph WITHOUT the catalog — nobody else (Marquez/Lakekeeper) does this.
22. ✅ **Persist + gate `/events` — DONE.** Moved the feed from the in-memory `deque(500)` to a durable
    `public.lineage_events` table (plain SQL in the same Postgres that hosts AGE; `ensure_events_table`
    on boot, `record_event` on ingest, `list_events` for the feed). **Gated** like the per-dataset reads:
    `DatasetFilter` drops any event referencing a dataset the caller can't `can_get_metadata` (auth-off →
    pass-through). **Proven durable** by a restart-survival test (24 events survive `docker restart`; was
    0 before). Reset script now drops the table too. Unit test for the gate + 140 unit/integration pass.
    (Retention is a fast-follow once it's a high-volume log.)
23. ✅ **Storage-version reconciliation — DONE (the format-aware moat).** New gated
    `GET /datasets/{name}/reconcile` cross-checks the version the graph recorded on the `WROTE` edge
    (`latest_write_version` = most-recent *successful* write, monotonic) against the **actual on-disk
    Lance version** read straight off object storage (`services/lineage/core/reconcile.py`, `read_storage_version` in
    the threadpool so blocking I/O never stalls the loop) and classifies drift: `in_sync` / `storage_ahead`
    (a write that bypassed lineage) / `graph_ahead` (a lineage claim with no data) / `untracked` /
    `missing_on_storage` / `absent`. Gated on `can_get_metadata` for `name` (in the route-gate set test).
    Shared `storage_options(settings)` promoted out of the demo module (config.py); demo reuses it.
    **Proven live** on the medallion stack: bronze v1==v1, silver v2==v2 (proves it picks the latest
    write, not v1), gold v1==v1 all `in_sync`; unknown dataset → `absent`. Drift paths covered by the
    parametrized core test + the endpoint-wiring test. Marquez/Lakekeeper are format-unaware and cannot
    do this. **Fast-follow:** version diffing (schema + row delta between two Lance versions, and which
    run caused it) + persist-schema-per-version (the #24 prerequisite).
24. ✅ **Column-level lineage (L — the one real feature) — DONE (backend; UI is the one remaining sub-task).**
    The deepest moat: field-to-field provenance neither Marquez nor Lakekeeper derives. Built end to end,
    design locked by a judge-panel workflow + an adversarial review workflow:
    - **Prerequisite (schema-per-version)** ✅ — ingest persists each output's column schema (JSON-string
      scalar) on the `WROTE` edge; `GET /datasets/{name}/schema?version=N`. (caught+fixed a string-vs-int
      version-match bug the read-coercion had masked.)
    - **Emit** — `services/lineage/seed.py` declares the standard `columnLineage` facet across the medallion
      (embedding←payload TRANSFORMATION, caption←embedding *same-dataset*, identity pass-throughs).
    - **Model** — `Dataset.column_edges` parses the facet (modern `transformations[]` + deprecated
      fallback; `masking = any()`).
    - **Graph** — `(:Column {dataset, field, namespace, type})` MERGEd on the 2-tuple (no concat id),
      `(:Dataset)-[:HAS_COLUMN]->(:Column)`, **distinct** `(:Column)-[:DERIVED_FROM_COLUMN]->(:Column)`
      (output→input). Ingest is success-only, seeds the full typed column set, stubs input columns
      (namespace only — never clobbers type), KEEPS same-dataset cross-field edges, skips only the true
      identity self-loop, all AGE-1.5.0-safe (separate edge-prop SET, scalar props incl. `masking` bool).
    - **Query + API** — `GET /datasets/{name}/columns/{field}/upstream|downstream` (transitive field
      provenance/impact) + `GET /datasets/{name}/columns` (the column DAG: typed nodes + edges with
      transformation kind + masking). Gated via `require_metadata_access`; **governed** — a column inherits
      its owning `table:<dataset>` visibility; related columns/nodes/edges touching a hidden dataset are
      dropped (edge needs BOTH endpoints visible), reusing the audited `_governed()`.
    - **Proven live**: `gold$catalog.caption` upstream → bronze.payload(blob)/silver.embedding/silver.caption
      with types; `bronze$events.payload` downstream → silver+gold columns; the `/columns` DAG shows the
      same-dataset `embedding→caption` edge. 163 unit + **2 e2e against live AGE** + 3 curl checks green.
    - ✅ **UI DONE (2026-06-30)**: the column-lineage **Columns** view (`ColumnNode.svelte` + `+page.svelte`
      tab, live poll, masking edges) renders the field-to-field DAG; `bun run check` clean. Still unblocks
      **schema-diffing between Lance versions** (#23 fast-follow).
    (supersedes P2 #12b)
25. 🟡 **Event-driven runtime — MOSTLY BUILT.** (a) Catalog→lineage transport is **Dapr pub/sub**
    (`DaprEmitter` → `pubsub.jetstream`; `handle_cloud_event` subscription) — sidecar owns
    retry/DLQ/trace-propagation, no broker client in app. (b) **The medallion cascade is event-driven**:
    `services/medallion/` — a `producer` (lance-ray head) + 3 stage `mover`s, each subscribing to its
    upstream trigger via Dapr, emitting OpenLineage (the `DERIVED_FROM` edge), publishing the next trigger,
    with FGA gating + one distributed trace raw→gold. (c) ✅ **Fake-Ray compute DONE (2026-06-30)** —
    `medallion/services/compute.py` (`seed_raw` + `transform_stage`) gives each stage a **real in-process
    Lance write** (gated `MEDALLION_COMPUTE_ENABLED`, default off), so the loop produces **actual versioned
    data**, not just provenance — the emitted lineage carries the real version. Same read→transform→write→
    version contract the distributed **lance-ray** (rask KubeRay, P1 #6) swaps into. 8 tests (real Lance).
    **Remaining (needs the live kind+Dapr stack):** S3 ObjectCreated input-binding trigger + a **Dapr-Workflow**
    gold QC gate (`docs/image-pipeline-event-driven.{html,md}`); and swapping the fake compute for real
    distributed lance-ray at the rask merge.
26. 🔶 **k8s (kind) + Helm + Tilt + Dapr platform — IN PROGRESS (the big migration, modeled on `rask/`).**
    Goal: a working running event-driven example on **kind** with frontend + **Apache-AGE Postgres** +
    **NATS** (events/pubsub via Dapr) + **OpenFGA (in Postgres)** + **Dex (OIDC)**, deployed by ONE
    umbrella Helm `chart/` (infra as gated subchart deps) and iterated with **Tilt** live-reload; **k9s**
    to inspect. Decisions: Dapr pub/sub (not nats-direct), kind (not k3s — Docker-only), Tilt (not
    Skaffold), **OpenBao** Dapr secret store = a later phase. Toolchain installed in `.localbin/`
    (kind/kubectl/k9s/tilt; helm on PATH). **Done:** the Dapr app-code pivot (#25 phase 1, commit 9b1c5f5).
    **Next:** author `chart/` (Chart.yaml deps dapr+nats+openfga; Dex + AGE-StatefulSet + dapr pubsub
    Component + subscription; values toggles; service Deployments w/ `dapr.io/*` annotations; Tiltfile;
    Makefile kind/tilt targets) → `helm lint`/`template` → kind deploy → verify with k9s → OpenBao.

**Cheap spec-fidelity facets (Marquez-ingestable, low effort):** `outputStatistics` (rows/bytes on WROTE)
and `lifecycleStateChange` (the carrier for #19's write events) are near-term load-bearing; `dataQuality`
assertions (the gold QC gate), `nominalTime`, `parent-run`, `processing_engine` are informational.

**Deliberately NOT doing (thesis-aligned rejections, not gaps):** namespace CRUD / multi-tenancy switcher
(we have unified id + FGA grants); imperative PUT seeding (breaks anti-forgery); symlinks/aliasing (breaks
one-identity); mutable description/tag CRUD (body-trusted). Full 25-gap matrix lives in the
`marquez-verdict` workflow transcript.

**Suggested next order:** ✅ #20 (version facet) → ✅ #21 (lineage↔data key) → ✅ #19 (emit on all
writes) → ✅ #22 (`/events` durable+gated) → ✅ #23 (storage-version reconciliation) → ✅ #24
(column-level lineage backend — field-to-field `(:Column)-[:DERIVED_FROM_COLUMN]->` + gated/governed
queries; only the Svelte UI remains) then **#25** (the Dapr/NATS event-driven runtime — the stated end goal).

---

## Lakekeeper — reference only (audited `~/Desktop/lakekeeper-ref`, 2026-06-25)

We are **doing our own thing: a Lance lakehouse + in-service lineage (OpenLineage→AGE) + governance
(OIDC/OpenFGA), with the microservices wired on Dapr.** Lakekeeper (Iceberg REST catalog, same OIDC+
OpenFGA stack) is a **reference, not a target** — **Lance only; no Iceberg, no generic tables, not a
general catalog.** The one useful fact from reading its code: it has **NO lineage** (`grep
lineage|openlineage|provenance` over all crates = 0 hits; its docs say to build lineage *on its event
stream*) — so **lineage is our moat**, confirmed in code. Everything else it ships (multi-warehouse,
soft-delete, contract hooks, user/role admin, task queue) is **out of scope** — recorded here only so we
don't re-evaluate it: it is NOT our roadmap.

### Postgres: why it's here, and the Lance-only option
**The catalog needs ZERO Postgres** — it is pure Lance on S3 (verified: `services/catalog/` has no DB dependency). The
**only** Postgres in the stack is the **lineage graph**, because it runs on **Apache AGE**
(`apache/age:PG16` — literally "A Graph Extension" *for* Postgres; `services/lineage/core/age.py`). AGE buys a durable
property graph + openCypher (`DERIVED_FROM*1..` upstream/downstream in one query). For **zero Postgres /
100% Lance**, the alternative is storing lineage **as Lance tables** (`runs`, `edges`) and traversing
in-app via DataFusion — at the cost of hand-rolling the recursive walk AGE gives free. **OPEN DECISION:** keep
AGE, or go Lance-native lineage. (OpenFGA's own store can be SQLite — not a Postgres reason.)

### Dapr is the chosen runtime for the microservices — what it gives us
Per the plan the services run on **Dapr** (sidecar building blocks), so this infra is *config, not
hand-rolled code*:
- **secrets (#7)** → `secretstores.*` (Vault/OpenBao/cloud) via the Dapr Secrets API — pluggable backend.
- **pub/sub (#25 transport + lineage event ingest)** → `pubsub.jetstream` — CloudEvents-native, DLQ +
  at-least-once for free, NATS↔Kafka swappable by config.
- **gold QC gate (#25)** → **Dapr Workflow** — durable, activity-checkpointed promotion.
- **S3 ObjectCreated trigger (#25)** → Dapr **input binding** (`bindings.aws.s3`) — no poller code.
- **scheduled / queued jobs** → Dapr **Jobs API** + Workflow.
- **cross-cutting** → sidecar **resiliency** (retry/timeout/circuit-breaker), **mTLS** service-to-service,
  auto **OTel** traces/metrics.
Dapr does NOT touch the core logic — Lance ops, the AGE graph, the OpenFGA model, and the STS credential-
vending app-logic (#5) stay app-level. It is the **service-layer runtime**, adopted before/with #25.

---

## Security & consistency backlog (verified — audit `w8u4rc2tg`, 5/9 high-criticals confirmed)
Severity in brackets; "latent" = real but not live today (lineage svc undeployed).
- ✅ **[high]** Lineage **read** endpoints unauthenticated → data-estate disclosure. **FIXED** —
  OIDC + `can_get_metadata` gate + `batch_check` transitive-disclosure filter (`services/lineage/api/{security,fga_deps}.py`). → **P0 #1**.
- ✅ **[high→latent]** Lineage **ingest** unauthenticated + `author` **self-asserted** → forgeable
  audit graph. **FIXED** — ingest requires a verified token; `enforce_author` binds `author`=`token.sub`
  (`services/lineage/api/{security,fga_deps}.py`, `services/lineage/main.py`). → **P0 #2**. *(Remaining: optional output-scoped ingest authz.)*
- ✅ **[high]** Catalog emitted **no lineage** → no audit record of who created a table. **FIXED (create)** —
  catalog emits create-lineage with the verified author → `(:User)-[:CREATED]->(:Dataset)` + `/creator`
  (`services/catalog/core/lineage_emit.py`). → **P0 #3**. *(Remaining: insert/delete/compaction → P2.)*
- **[low→latent]** Lineage hardcodes `$` while catalog delimiter is configurable → cross-axis identity
  mismatch (`services/catalog/core/config.py:28` vs `services/lineage/seed.py`). → **P0 #4 / P1 cleanup**.
- ✅ **[resolved — HCP dropped]** The old "HCP has no STS / static-keys-only" constraint no longer
  applies: the target is **S3-compatible only** (MinIO/Ceph/AWS), all of which implement STS. `StsVendor`
  is the recommended path → **P1 #5**.
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
