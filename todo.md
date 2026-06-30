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
   bind regresses a test. *(Remaining: optional FGA authz that the producer may write the named
   outputs — attributable today, not yet output-scoped.)*
3. ✅ **Catalog emits lineage on create** with `author` = the verified `token.sub` — "who created
   the table" is now an audit fact: a `(:User)-[:CREATED]->(:Dataset)` edge, queryable at
   `GET /datasets/{id}/creator`. Fire-and-forget + best-effort (never blocks/fails a write), default
   OFF (`LANCE_LINEAGE_EMIT_ENABLED`), canonical id (lineage Dataset == OpenFGA object id).
   `services/catalog/core/lineage_emit.py`, `services/catalog/api/v1/endpoints/data.py`, `services/lineage/models.py`, `services/lineage/services/repository.py`, `services/lineage/main.py`.
   *(Remaining → P2: emit on insert/merge/delete/compaction + Lance-version linkage.)*
4. 🟡 **Identity-consistency** — the catalog now emits lineage via `fga.canonical_object_id`, so a
   catalog-created Dataset name == its OpenFGA object id under any delimiter. **Still TODO:** the
   `services/lineage/seed.py` demo emitter hardcodes `$`, and a byte-identical cross-axis test under a
   non-default delimiter. Touch: `services/lineage/core/config.py`, `services/lineage/seed.py` + a test.

### P1 — needed for prod
5. ⛔ **Wire the credential vendor** into `describe_table?vend_credentials=true`
   (OpenFGA-tiered: `can_read_data`→read, `can_write_data`→write). Default OFF. `services/catalog/core/vending.py`, `services/catalog/api/v1/endpoints/data.py`.
   **`StsVendor` is the recommended path** (MinIO/Ceph/AWS all implement STS `AssumeRole` + inline
   session policy → short-TTL table-scoped creds). `mode_b` (server-mediated) stays the safe OOTB
   default; `static` for S3 backends without STS (GCS interop). Point the STS client at the S3
   endpoint via `LANCE_S3_STS_ENDPOINT` + `LANCE_S3_ASSUME_ROLE_ARN`.
6. ⛔ **lance-ray promotion + compaction jobs** (bronze→silver→gold) on the KubeRay cluster,
   using the Mode-B/vending data plane **and** emitting OpenLineage (template: `services/lineage/seed.py`).
   This is the medallion flow end-to-end.
7. ⛔ **OpenBao SecretStore** (KV v2): move catalog base storage cred + OIDC client secret +
   OpenFGA/AGE DB creds out of env; lineage AGE DB creds. lance-ray = **workload identity** (no Bao).
8. ✅ **Deploy lineage** — `lineage-api` service (`.docker/docker-compose.governance.yml`, same image)
   + `COPY lineage` in the dockerfile. Bring up the full stack + verify: `scripts/governance_e2e.sh`.
9. ⛔ **Routes-vs-spec conformance test** — FastAPI routes ⊆ lance-namespace spec ops.
10. ✅ **Lineage version linkage** — the `WROTE` edge carries the Lance **version** each run
    produced (OpenLineage `version` facet → `producers().dataset_version`), so refinement passes
    (silver v1 → v2) are distinguishable and provenance lines up with time-travel. In-place refines
    bump the version instead of creating a self-`DERIVED_FROM` edge. `services/lineage/models.py`, `services/lineage/services/repository.py`.

### P1 — verified security/consistency cleanups (audit `w8u4rc2tg`)
- ⛔ **OpenFGA tuple cleanup on drop / deregister / rename** — `services/common/fga.py` is **write-only**
  (`write_tuples` issues `ClientWriteRequest(writes=…)`, no deletes); `drop_table`/`deregister_table`/
  `drop_namespace`/`rename_table` leave stale `owner`/`parent` tuples → **stale-grant privilege bleed**
  if an id is reused. Add a `ClientWriteRequest(deletes=…)` path + call on drop/deregister/rename.
  **✔audit**. Touch: `services/common/fga.py`, `services/catalog/api/v1/endpoints/tables.py`, `namespaces.py`.
- ⛔ **Wire or remove unused `can_list` / `can_alter` / `can_commit` / `can_rename`** — defined in
  `services/common/auth/model.fga` but `fga_deps.py` never checks them (rename→`can_write_data`, list→`can_get_metadata`).
  Maintenance hazard: the model advertises finer granularity than enforcement implements. **✔audit**.
  Touch: `services/catalog/api/fga_deps.py`, `services/common/auth/model.fga`.

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
    - **Remaining sub-task**: the column-lineage **UI** (Svelte Flow field-to-field view) — backend is
      complete. Also still unblocks **schema-diffing between Lance versions** (#23 fast-follow).
    (supersedes P2 #12b)
25. 🔶 **Event-driven runtime — IN PROGRESS (Dapr transport landed).** Phase 1 DONE: the catalog→lineage
    transport is **Dapr pub/sub** (`DaprEmitter` → `pubsub.jetstream` component; `handle_cloud_event`
    Dapr subscription on the lineage side) replacing best-effort `BackgroundTasks` — the sidecar owns
    retry/DLQ/trace-propagation, app holds no broker client. Still designed-not-built: S3 ObjectCreated →
    NATS → Ray bridge → **Dapr-Workflow** gold QC gate, OpenLineage at every hop
    (`docs/image-pipeline-event-driven.{html,md}`).
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
