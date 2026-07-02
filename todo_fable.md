# todo_fable — complete fix backlog from the 2026-07-02 comprehensive audit

Source: two adversarially-verified workflow audits (108 agents; 99 findings verified: **91 confirmed**, 6 refuted
as documented demo defaults). Every item below is confirmed with file:line unless marked otherwise. Full raw
detail: workflow journals `wf_c253c55f-52f` (9-dimension) + `wf_e2c6583b-05a` (Dapr) under
`~/.claude/projects/-home-blackwell-Desktop-lance-ns/587d8935-4b16-4bc6-bed7-713ecf01a55d/subagents/workflows/`.

**Legend:** ⛔ not started · P0 security/correctness now · P1 before rask merge / any prod use · P2 quality+perf · P3 nit/doc

---

## 1 · P0 — security / correctness holes

- ⛔ **Reconcile cron route reachable unauthenticated through the gateway** — the gateway 403-blocks only
  `/lineage/lineage-events`; the `/lineage/` proxy rides Dapr service invocation which stamps the same
  `dapr-api-token` header `require_dapr_token` trusts, so an external caller can trigger graph-mutating
  back-fills. Found independently by 3 agents. Fix: gateway block for the reconcile route (and any future
  Dapr-delivered route — make the block list derive from one source). `chart/templates/gateway.yaml:49-50`
- ⛔ **Reconcile route mount vs token-assert flag decoupling** — the cron route mounts on
  `reconcile_binding_name` but the fail-closed boot assert only checks `dapr_enabled`; the flags can diverge,
  leaving the route mounted with no token verification. Tie the assert to “any sidecar-delivered route mounts”.
  `services/lineage/main.py:177`
- ⛔ **`observability-s3` Secret always ships the plaintext RustFS root secret** — not gated by
  `externalSecrets`, so the “0 plaintext secrets on the prod-secure path” guarantee is defeated.
  `chart/templates/observability.yaml:12`
- ⛔ **`values-prod.yaml` ships a known-constant app-token placeholder** (`REPLACE-ME-with-a-real-secret`) and
  nothing fails render/boot if the operator forgets to override — the forgery guard on every sidecar-delivered
  route would rest on a public string. Add a `fail`-template guard. `chart/values-prod.yaml:57`
- ⛔ **`values-prod.yaml` ships dev credentials if applied literally** — flips `openbao.devMode=false` but
  neither enables externalSecrets nor overrides `age.password`/`rustfs.secretKey` (`lance`/`rustfsadmin` land
  in infra + observability Secrets). Guard or document hard. `chart/values-prod.yaml:52`
- ⛔ **Demo data-peek router force-enabled with no auth and no off-switch** — `LINEAGE_DEMO_DATA_ENABLED`
  hardcoded `"true"` in every deployment; endpoints carry no OIDC/FGA guard → unauthenticated metadata
  disclosure bypassing the governance layer. Make it a values toggle, off in prod. `chart/templates/services.yaml:178`
- ⛔ **`/produce` exposed unauthenticated through the gateway** — an external caller can trigger cascades and
  inject forged medallion provenance (sidesteps `enforce_author`, which only guards HTTP ingest).
  `chart/templates/gateway.yaml:52`
- ⛔ **`authorize` tier-downgrade via path truncation** — the catalog guard derives the action tier from
  `request.url.path`, which Starlette truncates at decoded `#`/`?`, collapsing owner-tier ops
  (drop/deregister) to the writer-tier `can_write_data` check for exotically-named tables.
  `services/catalog/api/fga_deps.py:234`
- ⛔ **`require_dapr_token` uses `!=`** — timing side-channel on the only guard of the sidecar-delivered
  routes; switch to `secrets.compare_digest` (+ modern Annotated Header form). `services/common/dapr_auth.py:29`
- ⛔ **Vault secret-store component sets `skipVerify: "true"` unconditionally** — the wired
  `openbao.externalAddr` prod path (external HTTPS Vault) gets zero TLS verification for the component that
  fronts every app secret. Make it conditional. `chart/templates/dapr-component.yaml:70`

## 2 · P1 — Dapr / bus correctness (before scaling any subscriber past 1 replica)

- ⛔ **No `queueGroupName` on pubsub.jetstream → replicas get DUPLICATE delivery, not competing consumers.**
  Verified against components-contrib source (release-1.16 + 1.18). Contradicts `values.yaml:280,325-326`
  comments; `values-prod.yaml:24` sets `moverReplicas: 2` → each stage runs every trigger twice (up to 8× at
  gold). Fix: one pubsub component per subscriber app-id with `queueGroupName=<app-id>` (a single shared
  component can’t — one queue group would split messages ACROSS app-ids), or pin subscriber replicas to 1 and
  fix the comments. `chart/templates/dapr-component.yaml:16`
- ⛔ **`deliverPolicy` defaults to `all`** — every sidecar restart replays the full 168h stream into a fresh
  ephemeral consumer. Safe for lineage MERGE; NOT safe for the cascade head + movers (re-fired cascades,
  version churn). Set `deliverPolicy: new` for trigger consumption (or durable PULL consumers — the
  RESILIENCE.md roadmap item). `chart/templates/dapr-component.yaml:18`
- ⛔ **`backOff[0]=1s` silently overrides `ackWait=30s`** — effective ack window before first redelivery is
  1s; any handler slower than ~1s gets concurrently-redelivered duplicates even at 1 replica. Align backOff
  with real handler latency. `chart/templates/dapr-component.yaml:23`
- ⛔ **NATS backbone has no externalization path + is a prod SPOF** — `natsHost` hardcoded to the in-cluster
  subchart, streams created `--replicas 1`, and `nats.enabled=false` leaves the component pointing at dead DNS
  with no streams. Add external NATS hooks + stream replicas for prod. `chart/templates/nats-stream-job.yaml:36`
- ⛔ **Catalog never sets `DAPR_API_TIMEOUT_SECONDS`** — its inline-awaited lineage publish has no gRPC
  deadline; a wedged sidecar/NATS hangs every catalog write (create/insert/update/delete) indefinitely. Same
  root cause as `lineage_emit.py:324` (publish carries no deadline). `chart/templates/services.yaml:42`,
  `services/catalog/core/lineage_emit.py:324`
- ⛔ **Compaction cron Component renders without a `dapr.enabled` gate** — `--set dapr.enabled=false` emits a
  `dapr.io/v1alpha1` Component into a cluster with no Dapr CRDs → release fails to apply.
  `chart/templates/compaction.yaml:8`
- ⛔ **No `dapr.io/sidecar-cpu/memory` annotations on any of the 8 sidecar’d deployments** — every daprd runs
  unbounded while app containers are bounded (project’s own convention specifies limits). `chart/templates/services.yaml:21`
- ⛔ **Dapr placement + scheduler control-plane deploy by default** though the chart uses no actors/workflows/
  jobs/state store — disable in the subchart values. `chart/values.yaml:48`
- ⛔ **FGA outage exits `handle_stage` via unhandled `ServiceUnavailableError`** instead of the explicit RETRY
  contract — redelivery only happens because a 5xx is incidentally retriable. Catch → return `_RETRY`.
  `services/medallion/services/transform.py:60`

## 3 · P1 — OpenLineage spec fidelity (breaks the Marquez-reuse goal)

- ⛔ **Run IDs are not UUIDs** (`{operation}-{token}`) — violates the spec’s `run.runId` format; Marquez
  rejects them outright. Mint UUIDs, keep the token as a run facet for correlation.
  `services/medallion/services/produce.py:60` (+ transform.py, lineage_emit.py run-id sites)
- ⛔ **Top-level `schemaURL` missing from both hand-built RunEvent builders** — spec marks it REQUIRED on every
  event. `services/catalog/core/lineage_emit.py:119` (+ `services/medallion/schemas/events.py`)
- ⛔ **Custom `lance` + `author` run facets lack `_producer`/`_schemaURL`** — REQUIRED on every facet, standard
  or custom. `services/catalog/core/lineage_emit.py:97`
- ⛔ **Medallion events never emit the `dataSource` facet** → compute-written datasets carry no `source_uri`,
  so the B4 reconcile back-fill silently skips exactly the datasets the cascade writes. Emit it when compute
  is on (the URI is known). `services/medallion/schemas/events.py:56`
- ⛔ **Cascade head ignores `eventType`** — any raw-output event (incl. a spec-standard producer’s START or
  FAIL) fires the pipeline off data never (yet) written. Filter on COMPLETE.
  `services/medallion/services/ingest_trigger.py:35`
- ⛔ **A mover’s compute failure never emits a FAIL RunEvent** — once redelivery exhausts, the failed run is
  unrecorded in lineage (violates “record failed runs”). `services/medallion/services/transform.py:143`
- ⛔ **Quality assertions serialize `"column": null`** — fails strict validation against
  `DataQualityAssertionsDatasetFacet` (column is `string`); omit the key instead.
  `services/medallion/services/transform.py:118`
- ⛔ **Partial outputStatistics persists `-1` for the missing half** — producers() then serves a fabricated
  measurement; store None/omit. `services/lineage/models.py:128`
- ⛔ **Catalog job identity is the bare operation name** (`insert`, `create_table`) — every table’s writes lump
  into one Job node, which the /jobs governance rule then hides from nearly everyone. Namespace the job name
  per table (e.g. `create_table.bronze$events`). `services/catalog/core/lineage_emit.py:124`
- ⛔ **Synthetic RECONCILED back-fill run diverges across views** — written without `r.job`/`r.outputs` and
  never inserted into the events feed: /runs (governed) hides it, producers() shows it, /events never knows
  it. Stamp job/outputs + insert a feed row. `services/lineage/services/repository.py:176`
- ⛔ **Re-emitted duplicates defeat the /events natural key** — `build_run_event` stamps a fresh `eventTime`
  per attempt, so RETRY-after-partial-success inserts duplicate feed rows despite same run_id. Derive
  eventTime deterministically or widen the dedup key. `services/medallion/schemas/events.py:131`
- ⛔ **“Any raw writer (this dummy, or the catalog) can drive the head” claim is false as shipped** — a catalog
  write to the raw table can never match the loop-guard filter (namespace/dataset mismatch). Fix the filter or
  the claim. `services/medallion/producer.py:7`

## 4 · P1 — reliability / ACID

- ⛔ **Frontend `poll()` = 1+N+P+3 SEQUENTIAL calls per 2s tick** (N+1 over /datasets; 35+ calls at current
  scale), no overlap guard, no fetch timeout → slow ticks stack unboundedly. Batch (Promise.all), guard
  overlap, add timeouts; consider a bulk endpoint. `frontend/src/lib/store.svelte.ts:51`
- ⛔ **`backfill_write` is NOT transactional** — 3 Cypher statements on an autocommit connection (unlike
  `ingest_event`’s single transaction); crash mid-back-fill leaves a RECONCILED Run without WROTE/version.
  `services/lineage/services/repository.py:737`
- ⛔ **`create_table` is a 3-step dual-write with no compensation** (Lance create → FGA owner grant → lineage
  emit): FGA dying mid-way yields 503 whose retry hits “already exists” — table left with no owner tuple and
  no lineage. `services/catalog/api/v1/endpoints/data.py:103`
- ⛔ **Insert version attribution races** — WROTE version comes from a separate read-after-write
  (`current_version`); two concurrent inserts can both record the later version. Get the version from the
  write result / retry loop. `services/catalog/api/v1/endpoints/data.py:143`
- ⛔ **AGE pool: no health check, no statement timeout** — after Postgres failover the pool hands out dead
  sockets; a runaway `*1..` traversal pins a connection forever. Add `check` + `options='-c statement_timeout=…'`.
  `services/lineage/core/age.py:39`
- ⛔ **AGE graph: zero property indexes + Run nodes never pruned** — every MERGE (10–30 per ingest) and every
  fetch-all list seq-scans label tables that grow forever. Add indexes on the MERGE keys + a retention prune.
  `.docker/lineage-init.sql:7`
- ⛔ **`/events` over-fetch** — 2000 full-JSONB rows per call (frontend hits every 2s), sliced to 500 after
  governance; no cursor, no projection. `services/lineage/api/v1/endpoints/runs.py:21`
- ⛔ **`fetch_dapr_secret` blocks the event loop at boot** — sync `httpx.get` + `time.sleep` called from async
  lifespans; up to ~80s stall (10 × (5s timeout + 3s backoff)). Run in a thread or use async client.
  `services/common/secrets.py:38`
- ⛔ **Demo peek re-reads EVERY Lance version of every dataset per call** (one S3 dataset-open per version),
  polled every 2s — linear latency growth with cascade runs. Cache or cap versions. `services/lineage/api/v1/endpoints/demo.py:63`

## 5 · P2 — Python / FastAPI quality + consistency

- ⛔ **Catalog config comment lies about a fail-closed security invariant** — claims env is a boot-time
  fallback for the Dapr secret store; the lifespan implements strict fail-closed with NO env fallback. Fix the
  comment (twice: config docstring + settings field). `services/catalog/core/config.py:44`
- ⛔ **Compaction missing the boot guard its comment claims** — with `secrets_from_dapr` off, an empty
  `COMPACTION_S3_SECRET_ACCESS_KEY` boots silently (catalog has the guard; compaction doesn’t).
  `services/compaction/core/config.py:44`
- ⛔ **Fail-closed Dapr-secret splice copy-pasted 3×** (lineage, compaction, inline catalog lifespan) — move
  next to `fetch_dapr_secret` in `common/secrets.py`. `services/lineage/core/config.py:121`
- ⛔ **S3 secret is `SecretStr` only in catalog** — plain `str` in lineage/medallion/compaction; repr/dump
  leak-protection inconsistent. `services/lineage/core/config.py:66`
- ⛔ **Lineage lifespan teardown not isolated per-resource** — if `fga_client.close()` raises, `pool.close()`
  never runs (other 3 services use suppress-per-close). `services/lineage/main.py:88`
- ⛔ **`handle_stage` types `fga_client: Any`** though every caller passes `OpenFgaClient | None`.
  `services/medallion/services/transform.py:46`
- ⛔ **`_BACKFILLED` duplicates `_BACKFILLABLE`** — two must-agree private constants that can drift.
  `services/lineage/api/reconcile_cron.py:27` vs `services/lineage/core/reconcile.py`
- ⛔ **Catalog health probes are sync `def`** — they queue on the same 40-token threadpool as the blocking
  data plane; liveness fails exactly when the pod is busiest. Make async (they do no blocking work).
  `services/catalog/main.py:186`
- ⛔ **Medallion + compaction apps lack RFC 9457 handler parity** — `/produce` raises bare
  `HTTPException(503)` with default `{"detail": …}` and no Retry-After. `services/medallion/api/produce.py:25`
- ⛔ **`problem_detail` leaks internals on 500** — `str(exc)` lands in the response for INTERNAL-mapped errors,
  contradicting “internals leak via logs only”. `services/common/exceptions.py:70`
- ⛔ **medallion/compaction `/readyz` are static 200s** — no startup_complete/shutting_down lifecycle flags
  (catalog + lineage gate on lifespan state). `services/medallion/api/health.py:20`
- ⛔ **Docs-exposure policy inconsistent** — lineage/medallion/compaction serve `/docs` + `/openapi.json`
  unconditionally; catalog gates behind `LANCE_REST_DOCS`. `services/lineage/main.py:92`
- ⛔ **Emitter duplication** — HttpLineageEmitter/DaprEmitter duplicate identical `emit_create` bodies +
  9-kwarg `emit_write` signatures (~90 lines); NoopEmitter repeats a third time. Extract the shared body.
  `services/catalog/core/lineage_emit.py:199`
- ⛔ **`_s3fs` silently downgrades HTTPS to http** — strips both schemes then hardcodes `scheme="http"`.
  `services/compaction/services/sweep.py:34`
- ⛔ **Catalog endpoint handlers have no docstrings** (tables/namespaces/data/columns/indices/tags/branches/
  versions/transactions) while every lineage/medallion/compaction handler is documented.
  `services/catalog/api/v1/endpoints/tables.py:43`
- ⛔ **`governed()` erases element types** (`list[Any]`) — a PEP 695 generic keeps the type relationship free.
  `services/lineage/api/fga_deps.py:176`
- ⛔ **Same enum-setting constraint solved two ways in one file** — `lineage_transport` (str + validator) vs
  `vending_mode` (`Literal`). `services/catalog/core/config.py:107`

## 6 · P2 — dead config / dead exports / orphans

- ⛔ `values.yaml` **`dex.staticPassword` never read** — dex config hardcodes the bcrypt hash; changing the key
  silently does nothing. `chart/values.yaml:105`
- ⛔ `values.yaml` **`pubsub.route` never read** — the route is hardcoded in the lineage app AND the gateway
  403 regex (so it’s also a silently-diverging security config). `chart/values.yaml:309`
- ⛔ **Orphan scripts** — `scripts/seed_demo.sh` (its one mention, a config.py comment, misdescribes it) and
  `scripts/medallion_reset.sh` (referenced nowhere). Wire into Makefile/docs or delete.
- ⛔ **8 unused frontend type aliases** — DemoField, DemoVersion, ColumnRef, ColumnNode, ColumnEdge,
  JobSummary, Jobs, Namespaces (`frontend/src/lib/types.ts:15-29`). Note: JobSummary/Jobs/Namespaces are
  unused because **/jobs + /namespaces are not wired into the UI yet** — wire them into Browse (small win)
  or drop the aliases.
- ⛔ `RunEventEnvelope.is_failure` referenced only by tests. `services/lineage/models.py:281`

## 7 · P1/P2 — test coverage holes (add these tests)

- ⛔ **`common/dapr_auth.py` — ZERO tests at any tier** for `require_dapr_token` + `assert_app_token_configured`
  (the forged-CloudEvent guard whose docstring calls the unauthenticated path a prod-blocker). `services/common/dapr_auth.py:24`
- ⛔ **AGE-backed e2e not in CI** — CI runs `-m "not e2e"`; no job/Make target spins the AGE Postgres (the auth
  e2e DID get a docker-compose CI job — mirror it). `.github/workflows/ci.yml:39`
- ⛔ **/events Postgres surface never executes against a real DB** — record_event INSERT+prune, list_events
  SELECT, lineage_reads audit rows. `services/lineage/services/repository.py:802`
- ⛔ **`dataset_schema` real Cypher never exercised against AGE** — the code documents its own silent
  int-vs-string `$ver` failure mode that only a real-AGE test catches. `services/lineage/services/repository.py:633`
- ⛔ **`RunEvent.progress` + `_SET_PROGRESS` + /runs progress surfacing** — no test at any tier. `services/lineage/models.py:264`
- ⛔ **Reconcile cron route** (POST handler, OPTIONS ack, token wiring, response shape) — no test. `services/lineage/api/reconcile_cron.py:31`
- ⛔ **Demo router** (/demo/datasets Lance-on-S3 reads, per-version schemas, gold JSONB) — no behavioral test;
  Playwright mocks it empty. `services/lineage/api/v1/endpoints/demo.py:88`
- ⛔ **Frontend suites not in CI** — 3 Playwright tests + bun oidc-core tests run only manually. `frontend/package.json:15`
- ⛔ **/graph transitive-disclosure filter has no direct unit test** (its /columns twin tests both leak
  directions). `services/lineage/api/v1/endpoints/datasets.py:71`
- ⛔ **Live medallion e2e covers only the happy path** — FGA-gate DROP and quality-block never validated with
  real Dapr/NATS/AGE. `tests/e2e/test_medallion_e2e.py:48`

## 8 · P1/P3 — docs staleness (each would mislead a reader today)

- ⛔ **`docs/RASK-INTEGRATION.md:69` — the seam contract tells the future Ray job to publish `medallion.raw`
  itself → post-B2 that DOUBLE-FIRES the cascade.** Highest-stakes doc bug for the merge.
- ⛔ `docs/RASK-INTEGRATION.md:44` — claims producer+movers are “dummy emitters (provenance only, no data)”;
  stale since the B1 compute toggle.
- ⛔ `docs/ARCHITECTURE.md:56` — §2 describes vending via a nonexistent `describe_table?vend_credentials=true`
  param, “three pluggable shapes” (there are four), mis-states RustFS STS support.
- ⛔ `docs/ARCHITECTURE.md:263` — §8 marks lineage “🔶 deferred” while §7/§9 in the same doc say built+deployed.
- ⛔ `docs/ARCHITECTURE.md:220` — names a nonexistent Lance API `add_columns_from` (real: `add_columns`).
- ⛔ `docs/RESILIENCE.md:32` — gap #1 calls the catalog emit “fire-and-forget background task” (it’s awaited
  inline) and omits the shipped B4 back-fill that mitigates exactly this loss mode.
- ⛔ `docs/system-diagram.md:38` (+ .html) — stale “still open/planned” markers: insert/delete/compaction emit,
  lineage authz, OpenBao, vending — all shipped.
- ⛔ `docs/SYSTEM-SKETCH.md:72` — §2 says CredentialVendor “⛔ not wired”; §1 says “OpenBao (planned)” while §2
  says ✅ built.
- ⛔ `docs/DEPLOY.md:121-122` — footer denies the built RustFS STS path and calls the `make governed` demo
  “deployed-not-wired”.
- ⛔ `docs/COVERAGE.md:9` — headline tally stale (269/15 vs actual 304/17).
- ⛔ `docs/LINEAGE.md:206` — “Closing the loop: gold embeds its lineage as JSONB” reads as current pipeline
  behavior, but only the demo script writes the JSONB — the event-driven cascade does not. Reword (or make the
  silver→gold mover embed it when compute is on).
- ⛔ **Stale chart comments from pre-B2** — `chart/templates/medallion.yaml:6` (two comments say POST /produce
  publishes the first trigger) and `chart/values.yaml:280,325-326` (the false “competing consumers” claims —
  see §2).
- ⛔ **DLQ wording residual (from the refuted findings)** — `services/lineage/services/consumer.py:6`
  (“then dead-letters”), `services/medallion/services/transform.py:41` (“can dead-letter it”),
  `chart/templates/dapr-component.yaml:3` (header claims sidecar “owns retry/backoff/DLQ”): no deadLetterTopic
  is configured anywhere; behavior is stream-retention + restart replay. Fix wording or configure the DLQ.

## 9 · Feature gaps — ephemeral multimodal lakehouse (→ rask merge)

- ⛔ **P0 Multimodal (blob_v2) — MULTIMODAL FIRST.** The format + our pinned pylance>=7.0.0 fully support it
  (`lance/blob.py` BlobColumn, inline-when-small / pointer-when-large, ranged reads; verified in the installed
  package + lance_docs/{guide,file_format,ray}.md) and the direct write path (vended creds → RustFS) is open —
  but lance-ns has NEVER exercised a blob column. Dapr is uninvolved by design (events carry pointers, never
  data). Concrete work:
  - ⛔ P0 e2e proof: a blob column round-trips through OUR stack — write via vended creds → catalog registers →
    lineage captures schema/columnLineage → reconcile reads the version → ranged read back. No test exists.
  - ⛔ P0 guard the tabular path: the Arrow-IPC insert/query endpoints are wrong for blobs (2GB video over
    HTTP POST) — add a size guard + clear 4xx steering clients to the vending/direct path; document the rule.
  - ⛔ P1 serving path for credential-less consumers (frontend/browser): catalog endpoint doing a ranged blob
    read or presigned URL from a blob column — does not exist.
  - ⛔ P1 blob-pointer lifecycle: compaction/GC + reconcile must understand pointer columns referencing objects
    OUTSIDE the dataset dir (never GC them as orphans; flag dangling pointers after a bucket wipe).
  - ⛔ P2 quality gate blob assertion: "the blob pointer resolves" check alongside row_count/not_null.
  - ⛔ P2 per-project schema declaration (embeddings/classification/summarization columns are KNOWN per project):
    register expected columns so the quality gate asserts they landed, FGA pre-registers column masking, and
    reconcile flags undeclared writes — a governance contract, not a Dapr one. Lance itself needs no up-front
    schema (add_columns evolves it; per-version schemas already ride the WROTE edge).
  - ⛔ P1 enforce the claim-check invariant: events carry POINTERS (dataset/version/URI), never data — add a
    payload-size guard at every publish site + a doc'd rule "no base64/embeddings/data-shaped content in
    facets" (NATS default max message ~1MB; events must stay small JSON regardless of what the rows hold).
  - ⛔ P2 facet metadata bloat cap: a table with thousands of columns makes the schema/columnLineage facets
    themselves large (metadata bloat, not data bloat) — cap/truncate with a count + pointer to /schema instead
    of inlining every field, before rask-scale tables hit the message-size ceiling.
- ⛔ **P1 Ephemerality** — RustFS is `emptyDir` in this chart (pod roll wipes the lakehouse); at merge switch to
  rask’s RustFS-operator Tenant + CNPG-backed AGE. Prove “helm install from zero” fully reproducible
  (FGA seeds, OpenBao seeding, dex clients are still script-manual); backups exist but gated off.
- ⛔ **P1 Search** — `/search?q=` over datasets reusing rask’s Lance FTS+vector (`index_catalog.py` /
  `search_api` pattern); the *list* discovery API shipped in GOAL 4, semantic search did not. Also: wire the
  already-shipped `/jobs` + `/namespaces` into the Browse UI.
- ⛔ **P2 Compute seam completion** — Ray job submission surface + `parent` run facet (batch→chunk hierarchies)
  + real per-stage transforms; the fake-Ray contract (read→transform→write→version + emit) is in place.
- ⛔ **P2 Query engine** — DuckDB/DataFusion SQL over Lance + result cache: net-new (rask has neither), deferred
  by decision.
- ⛔ **P2 Control plane** — warehouse/project/role/user admin API (or CRDs following rask’s operator pattern);
  rask has no tenancy/operator of its own — this stays ours. FGA-as-registry + declarative seeding is the
  interim.
- ⛔ **P1 Externalization hardening** (ties to §1/§2): Vault skipVerify conditional, observability-s3 behind
  ESO, NATS external hooks + stream replicas, Dex→Keycloak swap = issuer/audience config only (verify no
  dex-specific claims parsing), OpenFGA stays in-cluster reusing rask’s subchart (we are its first consumer —
  flip datastore memory→postgres when adopted).
- ⛔ **P2 Lineage at rask scale** — `parent` facet ingestion, event-volume posture (AGE indexes + pruning from
  §4, /events cursor), `dataQualityMetrics` (deferred, costly on Lance).

## 10 · Explicitly refuted (do NOT re-report as bugs)

- “No DLQ = silent data loss” — refuted: Limits-retention streams (168h) + ephemeral-consumer restart replay
  recover exhausted messages idempotently; chaos-tested in docs/RESILIENCE.md; DLQ is a documented prod-roadmap
  item. Residual = wording fixes in §8.
- “Full-stream replay on restart is a defect” — refuted: documented trade-off (RESILIENCE.md gap #3) that fixed
  a worse durable-PUSH orphan bug; idempotent end-to-end. Residual = `deliverPolicy: new` for triggers (§2).
- “Token-less triggers duplicate Run nodes / stage RETRY re-runs are a bug” — refuted: token always set by every
  wired publisher, route token-guarded, whole-stage replay is the documented at-least-once design converging
  via MERGE + overwrite.
