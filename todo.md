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
- ✅ **HCP dropped → S3-compatible only** (MinIO default; AWS / Ceph RGW / RustFS / GCS-interop). Code +
  docs + diagram reframed to **Mode B (server-mediated) vs STS vending**. RustFS storage-agnostic e2e:
  `.docker/docker-compose.rustfs.yml` + `scripts/rustfs_e2e.sh` (same lifecycle test, bytes on RustFS).
- ✅ **Realistic medallion lineage sim + version linkage (P1 #10)** — `lineage/seed.py`: alice ingests
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
5. ⛔ **Wire the credential vendor** into `describe_table?vend_credentials=true`
   (OpenFGA-tiered: `can_read_data`→read, `can_write_data`→write). Default OFF. `app/core/vending.py`, `app/api/v1/endpoints/data.py`.
   **`StsVendor` is the recommended path** (MinIO/Ceph/AWS all implement STS `AssumeRole` + inline
   session policy → short-TTL table-scoped creds). `mode_b` (server-mediated) stays the safe OOTB
   default; `static` for S3 backends without STS (GCS interop). Point the STS client at the S3
   endpoint via `LANCE_S3_STS_ENDPOINT` + `LANCE_S3_ASSUME_ROLE_ARN`.
6. ⛔ **lance-ray promotion + compaction jobs** (bronze→silver→gold) on the KubeRay cluster,
   using the Mode-B/vending data plane **and** emitting OpenLineage (template: `lineage/seed.py`).
   This is the medallion flow end-to-end.
7. ⛔ **OpenBao SecretStore** (KV v2): move catalog base storage cred + OIDC client secret +
   OpenFGA/AGE DB creds out of env; lineage AGE DB creds. lance-ray = **workload identity** (no Bao).
8. ✅ **Deploy lineage** — `lineage-api` service (`.docker/docker-compose.governance.yml`, same image)
   + `COPY lineage` in the dockerfile. Bring up the full stack + verify: `scripts/governance_e2e.sh`.
9. ⛔ **Routes-vs-spec conformance test** — FastAPI routes ⊆ lance-namespace spec ops.
10. ✅ **Lineage version linkage** — the `WROTE` edge carries the Lance **version** each run
    produced (OpenLineage `version` facet → `producers().dataset_version`), so refinement passes
    (silver v1 → v2) are distinguishable and provenance lines up with time-travel. In-place refines
    bump the version instead of creating a self-`DERIVED_FROM` edge. `lineage/{models,repository}.py`.

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
12b. 🔶 **Column-level lineage** — producers emit OpenLineage `columnLineage` facets, but the AGE
    graph stores **dataset-level** edges only. Add `(:Column)` nodes + column-level edges so
    "which output column came from which input column" is queryable (the medallion seed already
    carries schema changes per pass: silver +`embedding`, then +`caption`).
13. 🔶 **Governance P1** — `project` type + 3-axis (teams × projects × layers); versioned
    OpenFGA-model migrations + reconcile-from-catalog (Lakekeeper patterns).
14. 🔶 **Async lineage ingest** (jobs → NATS → consume) · **Dapr** workflows · **OTel** traces/metrics.
15. ✅ **Live medallion demo + SvelteKit UI** — `scripts/medallion_demo.py` *executes* the flow against
    the real stack (RustFS + lineage/AGE): writes bronze (blob `payload`), adds `embedding` then
    `caption` to silver (Lance write + add-column → v1, v2), aggregates gold with the embedded
    `lineage` JSONB — each step emitting **real** OpenLineage. `--step N` lets you be the producer.
    UI = a **SvelteKit app** (`web/`, Svelte Flow + bits-ui on Bun) with three live views: Graph (DAG,
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
    - **[small new code] UI login flow** — the one genuinely-new piece: OIDC code-flow + session in the
      SvelteKit app so its `/api/*` proxy forwards a real `Authorization` bearer (today it polls
      unauthenticated). SvelteKit `hooks.server.ts` + a session cookie; lineage then verifies + filters.
    - **[small, backend] Harden demo endpoints for prod** — `/demo/datasets` (reads raw S3) is
      DEMO-ONLY → remove/keep flag-gated; `/events` is ungated in-memory → persist + gate like the
      per-dataset reads.
    - **[backend] Output-scoped ingest authz** — also check the producer may *write* the named output
      tables (`can_write_data`), not just that it's authenticated (currently attributable but not scoped).
    - **[data plane] Wire `StsVendor` into `describe_table?vend_credentials`** (P1 #5) — real per-table
      short-TTL creds on MinIO/Ceph/AWS (RustFS: mode_b/static until it supports inline policy scoping).
    Bottom line: **easy to add later** — enforcement code exists; the only build is the UI login flow.
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
19. ⬜ **Real catalog emits the full lifecycle, not just `create_table` (M).** `app/core/lineage_emit.py`
    has only `emit_create`; `data.py:79` calls it only on create — insert/merge/update/delete emit
    NOTHING (the rich flow exists only in `seed.py` / `medallion_demo.py`). Add `emit_insert/merge/delete`
    + wire the 4 call sites; each needs the resulting Lance version. (supersedes P2 #11)
20. ⬜ **version-on-WROTE in prod (S, decisive).** `build_create_event` puts version in a CUSTOM `lance`
    facet; `repository.output_version` reads the STANDARD per-output `DatasetVersionDatasetFacet` (only the
    demo emits it) → a real `create_table` persists `WROTE.version = NULL`. Fix: attach the standard
    version facet to each output in `build_create_event` (~3 lines, revives the storage-version edge).
21. ⬜ **Lineage ↔ data KEY embedded in the Lance file (self-describing data) — user request.** Today the
    only link is a *convention*: the canonical id (`Dataset.name`) + the version on WROTE. NOTHING is
    written into the Lance file at create (verified — `create_table` writes no table metadata); only gold's
    JSONB column, demo-only. **Build:** at `create_table`, write into Lance `schema.metadata` (± a column)
    `{lineage.dataset_id, lineage.namespace, lineage.create_run_id, lineage.created_by}` so the data
    carries its own OpenLineage coordinates and is reconcilable to the graph WITHOUT the catalog. Slots into
    `create_table` + `build_create_event` next to #20. NB: OpenLineage is per-`(namespace,name)`; we use the
    single canonical `name` as identity, so carry `namespace` as **annotation-in-file, not a 2nd id axis**.
22. ⬜ **Persist + gate `/events`.** `/runs` is now durable (#17); `/events` is still `deque(500)`,
    in-memory + UNGATED. Move to a durable store + reuse the `can_get_metadata` filter; add retention once
    it's a real log. (overlaps P2 #16)
23. ⬜ **Storage-version reconciliation.** `/demo/datasets` reads real Lance versions/schema off S3 but is
    demo-gated, hardcoded to 3 datasets, NEVER reconciled vs the AGE `WROTE.version`. Promote to a
    first-class gated capability that cross-checks emitted vs on-disk version + flags drift; then layer
    **version diffing** (schema + row delta between two Lance versions, and which run caused it).
24. ⬜ **Column-level lineage (L — the one real feature).** `SchemaDatasetFacet` is emitted but DISCARDED
    on ingest; AGE stores ZERO schema, no `(:Column)` nodes. Needs: the transform to DECLARE column→column
    mappings (`columnLineage` facet — not free), `(:Column)` nodes + field-to-field edges, ingest storage,
    query + UI. Persist schema-per-version first (prerequisite). (supersedes P2 #12b)
25. ⬜ **Event-driven runtime is designed, not built.** The medallion is a synchronous driver; the
    NATS JetStream + Ray bridge + Dapr-Workflow gold QC gate is the design in
    `docs/image-pipeline-event-driven.{html,md}` + `docs/event-driven-pipeline.{html,md}` (P2 #14). Build:
    S3 ObjectCreated → NATS → Ray bridge → Dapr gold gate, OpenLineage at every hop.

**Cheap spec-fidelity facets (Marquez-ingestable, low effort):** `outputStatistics` (rows/bytes on WROTE)
and `lifecycleStateChange` (the carrier for #19's write events) are near-term load-bearing; `dataQuality`
assertions (the gold QC gate), `nominalTime`, `parent-run`, `processing_engine` are informational.

**Deliberately NOT doing (thesis-aligned rejections, not gaps):** namespace CRUD / multi-tenancy switcher
(we have unified id + FGA grants); imperative PUT seeding (breaks anti-forgery); symlinks/aliasing (breaks
one-identity); mutable description/tag CRUD (body-trusted). Full 25-gap matrix lives in the
`marquez-verdict` workflow transcript.

**Suggested next order:** #20 (version facet, tiny) → #21 (lineage↔data key, pairs with #20) → #19 (emit
on all writes) → #22 (`/events` durable+gated, same move as `/runs`) → then #23/#24/#25.

---

## Lakekeeper code-audit (2026-06-25 — read the real Rust at `~/Desktop/lakekeeper-ref`)

**Lakekeeper = our closest peer** (Iceberg REST catalog; *same* stack we chose: OpenFGA + OIDC + Postgres
+ Vault + CloudEvents→NATS/Kafka). **Lineage is ABSENT in its code** (`grep lineage|openlineage|provenance`
over all crates = 0 hits; docs position lineage as something you build *on its change-event stream*). So
**lineage + Lance-native is our moat**, confirmed at the code level. But its **catalog plane is far deeper
than our todo tracks** — most of the following is NOT in our list:

26. ⬜ **Soft-delete + deletion-protection + undrop/recover.** Lakekeeper: `TabularDeleteProfile{Hard,
    Soft{expiration_seconds}}`; `protected` flag on warehouse/namespace/table (drop refused without
    `force`); `GET …/deleted-tabulars` + `POST …/undrop`; expiration + purge worker queues. We have NONE.
27. ⬜ **Contract-verification hook.** A trait that BLOCKS a catalog write (table/view update/drop/rename)
    violating a data contract/SLO → 409 `ContractViolation`, enforced *after authz, before the mutation*.
    Distinct from our pipeline gold-QC gate (which is a *job* gate, not a *catalog-write* hook).
28. ⬜ **User / role / permission management plane.** Provision + **fuzzy-search** users; roles + membership
    (assign/transitive); per-object grant/revoke **assignment API**; batch-check; whoami; bootstrap. We have
    OIDC *auth* + per-read FGA checks but **no management plane** to administer principals/grants.
29. ⬜ **Catalog change-event stream** (CloudEvents v1.0 per-table → NATS subject / Kafka topic keyed by
    `tabular-id`), `EventListener` + `CloudEventBackend` traits. Distinct from #25 (pipeline events): this is
    "the catalog emits a change event for every table op." **This is the integration point our lineage
    service should *consume*** (exactly how Lakekeeper says to build lineage). High-leverage.
30. ⬜ **Warehouse/dataset lifecycle + statistics.** deactivate/activate, format-version policy, managed-by;
    warehouse stats + per-endpoint API stats. Not tracked.
31. ⬜ **Generic durable task queue** (Postgres-backed: retries/heartbeat/status, built-in expiration/purge/
    log-cleanup). Generalises #6 (which is only specific Ray jobs).
32. 🔭 **STRATEGIC — Lance as a "generic table" on a Lakekeeper-style catalog?** Lakekeeper has a first-class
    `generic_table` FGA type + a `/lakekeeper/v1` data API *for non-Iceberg formats* (`CreateGenericTable`
    carries `format` + `base_location` — exactly Lance's shape). So the build-vs-reuse question sharpens:
    **register Lance as generic-tables → inherit its authz / credential-vending / soft-delete / events for
    free, and spend our effort on the lineage + Lance-native layer (which it lacks), consuming its CloudEvents
    stream** — vs reinventing #5/#6/#7/#13/#25 + #26–31. Decide this BEFORE sinking weeks into the catalog plane.

**Coverage of the shallow overlaps:** #5 (credential vending — ours is 1 line; theirs is STS AssumeRole +
downscoped session policy + external_id + session-tags + remote-signing + R2 + Azure-SAS + GCS-downscope,
prefix-scoped & verified at create) · #7 (Vault/kv2 — genuinely covered) · #13 (hierarchical FGA + role
model — ours is flat table-level; theirs is a 9-type server→project→warehouse→ns→table hierarchy + admin/
security_admin/data_admin roles + managed-access) · #6 (maintenance — partial; compaction is Enterprise even
in Lakekeeper) · #25 (events — ours is *pipeline*, theirs is *catalog change* = #29).

### Dapr lens — which of the above become *config, not code*
Dapr building-block **components** (sidecar) replace several hand-rolled infra layers Lakekeeper codes by
hand, so adopting Dapr **shrinks** these items to "declare a component + use the Dapr API":
- **#7 secrets** → Dapr `secretstores.hashicorp.vault` (or azure.keyvault/aws) — read via the Secrets API;
  swap backend by config. (Lakekeeper hand-codes a `kv2` crate; Dapr makes it pluggable.)
- **#25 transport + #29 catalog events** → Dapr `pubsub.jetstream` (or pubsub.kafka) — publish/subscribe
  via the Dapr pub/sub API; swap NATS↔Kafka by config; CloudEvents is Dapr's *native* envelope. (Lakekeeper
  hand-codes NATS + Kafka `CloudEventBackend`s; Dapr gives both + dead-letter + at-least-once for free.)
- **#25 gold QC gate** → **Dapr Workflow** (already planned) — activity-checkpointed durable promotion.
- **#25 S3 ObjectCreated trigger** → Dapr **input binding** (`bindings.aws.s3`/blob) or a Cron binding — no
  poller code.
- **#31 task queue** → Dapr **Jobs API** + Workflow — durable scheduled/queued tasks without a hand-rolled
  Postgres queue.
- **resilience / #-cross-cutting** → Dapr **resiliency policies** (retry/timeout/circuit-breaker) at the
  sidecar replace per-call `tenacity`; **mTLS** service-to-service; **OTel** traces/metrics auto-emitted.
Net: Dapr is a **meta-decision** that collapses #7/#25/#29/#31 (+ resilience/observability) into declarative
components — at the cost of a sidecar-per-pod. It does NOT touch the *core* logic (Lance ops, the AGE graph,
OpenFGA model, STS-vending app-logic in #5) — those stay app-level. Decide Dapr at the same time as #32
(both are "lean on a runtime vs hand-roll").

---

## Security & consistency backlog (verified — audit `w8u4rc2tg`, 5/9 high-criticals confirmed)
Severity in brackets; "latent" = real but not live today (lineage svc undeployed).
- ✅ **[high]** Lineage **read** endpoints unauthenticated → data-estate disclosure. **FIXED** —
  OIDC + `can_get_metadata` gate + `batch_check` transitive-disclosure filter (`lineage/auth.py`). → **P0 #1**.
- ✅ **[high→latent]** Lineage **ingest** unauthenticated + `author` **self-asserted** → forgeable
  audit graph. **FIXED** — ingest requires a verified token; `enforce_author` binds `author`=`token.sub`
  (`lineage/auth.py`, `lineage/main.py`). → **P0 #2**. *(Remaining: optional output-scoped ingest authz.)*
- ✅ **[high]** Catalog emitted **no lineage** → no audit record of who created a table. **FIXED (create)** —
  catalog emits create-lineage with the verified author → `(:User)-[:CREATED]->(:Dataset)` + `/creator`
  (`app/core/lineage_emit.py`). → **P0 #3**. *(Remaining: insert/delete/compaction → P2.)*
- **[low→latent]** Lineage hardcodes `$` while catalog delimiter is configurable → cross-axis identity
  mismatch (`config.py:28` vs `lineage/seed.py`). → **P0 #4 / P1 cleanup**.
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
