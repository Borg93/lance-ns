# todo_fable — complete fix backlog from the 2026-07-02 comprehensive audit

Source: two adversarially-verified workflow audits (108 agents; 99 findings verified: **91 confirmed**, 6 refuted
as documented demo defaults). Every item below is confirmed with file:line unless marked otherwise. Full raw
detail: workflow journals `wf_c253c55f-52f` (9-dimension) + `wf_e2c6583b-05a` (Dapr) under
`~/.claude/projects/-home-blackwell-Desktop-lance-ns/587d8935-4b16-4bc6-bed7-713ecf01a55d/subagents/workflows/`.

**Legend:** ⛔ not started · P0 security/correctness now · P1 before rask merge / any prod use · P2 quality+perf · P3 nit/doc

---

## 1 · P0 — security / correctness holes — ✅ ALL FIXED (2026-07-02)

- ✅ **Reconcile cron route reachable unauthenticated through the gateway** — FIXED: the gateway 403 block
  now renders from ONE source, the `lance.lineageSidecarOnlyRoutes` helper (`_helpers.tpl`) — an nginx regex
  alternation covering `/lineage-events` + the reconcile binding name; add any future Dapr-delivered lineage
  route there, not in `gateway.yaml`.
- ✅ **Reconcile route mount vs token-assert flag decoupling** — FIXED: `services/lineage/main.py` asserts
  `dapr_enabled OR reconcile_binding_name` — any sidecar-delivered mount without `APP_API_TOKEN` refuses to
  boot. Pinned by `tests/unit/test_dapr_auth.py::test_lineage_boot_fails_when_only_the_reconcile_route_mounts`.
- ✅ **`observability-s3` Secret always ships the plaintext RustFS root secret** — FIXED: static Secret now
  skipped when `externalSecrets.enabled`; a second ExternalSecret in `external-secrets.yaml` owns the
  same-named Secret (secret key from Vault, access-key id templated — it isn't sensitive).
- ✅ **`values-prod.yaml` ships a known-constant app-token placeholder** — FIXED: `dapr-app-token.yaml`
  `fail`s the render on the placeholder value AND on the base-chart dev-default token when
  `openbao.devMode=false` (parity with the age/rustfs guards — closes the diff-review gap where a
  hand-rolled prod overlay could ship the public dev token). Verified both cases fire.
- ✅ **`values-prod.yaml` ships dev credentials if applied literally** — FIXED: `infra-credentials.yaml`
  `fail`s the render when `openbao.devMode=false` (the prod signal) + dev-default `age.password` /
  `rustfs.secretKey` + no externalSecrets; values-prod documents the guards. Verified each fires.
- ✅ **Demo data-peek router force-enabled with no auth and no off-switch** — FIXED: values toggle
  `services.lineage.demoData` (dev default true), `false` in values-prod → the router never mounts.
- ✅ **`/produce` exposed unauthenticated through the gateway** — FIXED: gateway location gated on new
  `medallion.producer.expose` (dev demo true; values-prod false — the prod head fires only via `/raw-arrival`).
- ✅ **`authorize` tier-downgrade via path truncation** — FIXED: `authorize` reads `request.scope["path"]`
  (what routing matched) instead of `request.url.path` (re-parses and truncates at decoded `#`/`?` —
  repro'd on the installed Starlette before fixing). Pinned by
  `tests/integration/test_authz.py::test_hash_or_question_in_id_cannot_downgrade_the_owner_tier`.
- ✅ **`require_dapr_token` uses `!=`** — FIXED: `secrets.compare_digest` over BYTES (a non-ASCII header is
  a clean 403, not a TypeError) + Annotated Header form. `tests/unit/test_dapr_auth.py` now covers the whole
  module (was zero tests — also closes that §7 row).
- ✅ **Vault secret-store component sets `skipVerify: "true"` unconditionally** — FIXED: `skipVerify` now
  tracks the Vault address scheme — `false` for an https Vault (the `openbao.externalAddr` prod path),
  `true` only for the plain-http in-cluster dev OpenBao. Render-verified both ways.

## 2 · P1 — Dapr / bus correctness — ✅ ALL FIXED (2026-07-02; NOT yet live-verified on the cluster — re-run the chaos rows in RESILIENCE.md after the next deploy)

- ✅ **No `queueGroupName` → duplicate delivery** — FIXED with per-subscriber components: each subscriber
  app-id gets its own `pubsub.jetstream` Component (`lance.subPubsub` helper → `lineage-pubsub-<app-id>`)
  carrying `queueGroupName=<app-id>` + per-app scope; the bare `lineage-pubsub` is publish-only (catalog +
  compaction). The shared-component trap (one queue group splitting lineage.events.v1 across lineage and
  lance-ray) is documented in the helper. values.yaml replica comments corrected.
- ✅ **`deliverPolicy` defaults to `all`** — FIXED as a deliberate per-app split: `all` for lineage
  (restart-replay into idempotent MERGE = the durability story), `new` for the cascade head + movers (no
  restart-triggered cascade storms; missed-while-down triggers are the documented gap — RESILIENCE.md #3
  rewritten, durable PULL consumer stays the roadmap fix).
- ✅ **`backOff[0]=1s` overrides `ackWait=30s`** — FIXED: `backOff: 30s,60s,120s,300s` (first step = the
  effective ack window ≥ the slowest compute-on handler; ~8.5 min total), comment explains the NATS
  semantics. RESILIENCE.md numbers updated.
- ✅ **NATS externalization + SPOF** — FIXED: `nats.externalUrl` + `lance.natsUrl` helper (components +
  stream Job), `nats.streamReplicas` on the stream Job (needs clustered NATS — documented), Job also runs
  when external-only (`or nats.enabled nats.externalUrl`), values-prod EXTERNALIZE stanza added.
- ✅ **Catalog/lineage missing `DAPR_API_TIMEOUT_SECONDS`** — FIXED: both env blocks set it from
  `dapr.apiTimeoutSeconds` (7 pods total render it), so the inline-awaited catalog publish and the boot
  secret fetch carry a gRPC deadline.
- ✅ **Compaction cron Component no `dapr.enabled` gate** — FIXED (and the reconcile-cron Component got the
  same gate); `--set dapr.enabled=false` renders 0 Components.
- ✅ **No sidecar resource annotations** — FIXED: `lance.daprSidecarResources` helper (values
  `dapr.sidecarResources`) on all 8 sidecar'd deployments (render-verified 8×4 annotations).
- ❌ **Placement + scheduler deploy unused** — REVERTED (the audit finding is a FOOTGUN on Dapr 1.18):
  disabling them makes EVERY daprd sidecar hang `1/2` forever — daprd 1.18 connects to
  `dapr-placement-server` AND `dapr-scheduler-server-a` at startup unconditionally and never goes Ready
  without them (caught LIVE on helm rev 45: sidecars looping "no such host"). The control plane stays; the
  values comment now documents why NOT to disable it. (Only safe saving: shrink scheduler replicas 3→1.)
- ✅ **FGA outage → unhandled 500** — FIXED: `handle_stage` catches `ServiceUnavailableError` around the
  gate check → explicit `RETRY` (outage ≠ denial); pinned by
  `tests/unit/test_medallion.py::test_mover_retries_on_fga_outage`.
- Also fixed here: false “sidecar owns DLQ / dead-letters” claims corrected across 7 docstrings +
  DEPLOY.md (no `deadLetterTopic` exists — RESILIENCE.md gap #2 is the honest statement).

## 3 · P1 — OpenLineage spec fidelity — ✅ ALL FIXED (2026-07-02; verified vs installed openlineage-python)

New shared helper `services/common/openlineage.py` (`run_id_for` uuid5, `RUN_EVENT_SCHEMA_URL`,
`custom_facet`) — the single place that keeps the three hand-built builders spec-true. Spec claims
verified against the INSTALLED `openlineage-python` (RunEvent carries schemaURL; BaseFacet requires
_producer/_schemaURL) + a 6-case round-trip smoke test through `lineage.models.RunEvent`.

- ✅ **Run IDs not UUIDs** — FIXED: `run_id_for("<op>-<token>")` = deterministic uuid5 (spec-valid AND stable
  for idempotent MERGE); the readable token now rides the `lance` run facet. medallion produce+transform,
  reconcile back-fill. Catalog/compaction already used uuid4.
- ✅ **Top-level `schemaURL` missing** — FIXED on all three builders (`RUN_EVENT_SCHEMA_URL`).
- ✅ **Custom `lance`/`author` facets lack `_producer`/`_schemaURL`** — FIXED via `custom_facet(...)` on all three.
- ✅ **Medallion never emits `dataSource`** — FIXED: emitted from the stage TO_URI/raw URI when compute is on
  (unblocks the B4 reconcile for cascade-written datasets — a real functional bug, not just fidelity).
- ✅ **Cascade head ignores `eventType`** — FIXED: `_writes_raw` requires `eventType == COMPLETE`.
- ✅ **No FAIL RunEvent on compute failure** — FIXED, then CORRECTED after the 73af2fd review found two bugs
  in the first cut: (a) the FAIL now keeps a BARE output (name only) so the repo makes a WROTE edge and
  `producers()` surfaces the attempt — the first version emitted `outputs=[]`, which created no edge and left
  the failed run invisible in `producers()` (contradicting the repo contract + `seed.py`); (b) the FAIL is
  emitted ONLY when the transform actually failed (COMPLETE not yet emitted) — the first version emitted it
  from an except that ALSO covered the downstream trigger publish, so a post-COMPLETE trigger failure flipped
  a SUCCEEDED run to FAIL. Both pinned by new tests (`test_mover_emits_fail_event_on_transform_failure`,
  `test_mover_does_not_fail_run_when_only_the_trigger_publish_fails`).
- ✅ **`"column": null` in quality assertions** — FIXED: `Assertion.model_dump(exclude_none=True)` omits the key.
- ✅ **Partial outputStatistics persists `-1`** — FIXED: `statistics` returns `None` for the absent half.
- ✅ **Catalog job identity = bare op** — FIXED: `<operation>.<table_id>` (compaction too: `compaction.<id>`).
- ✅ **Synthetic RECONCILED run diverges across views** — FIXED: stamps `r.job` + `r.outputs` AND inserts a feed
  row (a spec-shaped RECONCILED event), so /runs, producers(), and /events agree. Deterministic uuid5 id.
- ✅ **Re-emitted duplicates defeat the /events key** — FIXED: a partial unique index on `(run_id, event_type)`
  for terminal types + targetless `ON CONFLICT DO NOTHING` dedups a redelivered terminal event regardless of
  its fresh eventTime, while RUNNING events keep the 3-col key so their progress trail survives.
- ✅ **False “any raw writer incl. the catalog” claim** — FIXED: `producer.py` docstring now states the head
  reacts specifically to a COMPLETE write matching `raw_namespace`/`raw_dataset` (not any catalog write).

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

- ✅ `values.yaml` **`dex.staticPassword` never read** — FIXED: removed the dead key; the comment now points
  at the real bcrypt hash in `templates/dex.yaml` + how to regenerate it (Helm can't bcrypt at render).
- ✅ `values.yaml` **`pubsub.route` never read** — FIXED with the §2 sweep: the dead key is removed; the
  pubsub comment now names where the routes actually live (app code) and the gateway block regex derives
  from the `lance.lineageSidecarOnlyRoutes` helper (§1), so there is no silently-diverging copy left.
- ✅ **Orphan scripts** — FIXED: `seed_demo.sh` was superseded by `governance_demo.py` (the docs-referenced
  authz demo) and its only mention was a *wrong* config comment → deleted the script + corrected the comment
  (the warehouse root is admin-bootstrapped, not seeded by that script). `medallion_reset.sh` is a current,
  useful companion to `medallion_demo` (reads `.medallion-demo.env`, still produced) → wired into the
  LINEAGE.md demo section, so it's discoverable, not orphan.
- ✅ **8 "unused" frontend type aliases** — STALE (nothing to do): all 8 (DemoField/DemoVersion/ColumnRef/
  ColumnNode/ColumnEdge/JobSummary/Jobs/Namespaces) are now used 3–8× — they got wired into the Browse /
  jobs / column-graph UI in GOAL 3/4, *after* the audit. Verified by grep across `frontend/src`.
- ✅ `RunEventEnvelope.is_failure` referenced only by tests — FIXED: dropped the unused property; its 2 test
  assertions now check `event_type` directly (keeps the FAIL-parse coverage). `is_success` stays (used 3×).

## 7 · P1/P2 — test coverage holes (add these tests)

- ✅ **`common/dapr_auth.py` — ZERO tests at any tier** — FIXED with the §1 sweep: `tests/unit/test_dapr_auth.py`
  covers `require_dapr_token` (open default, match, mismatch/missing/non-ASCII 403) + `assert_app_token_configured`
  (fail-closed, blank token, no-ops) + the lineage reconcile-mount coupling.
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

- ⛔ **P2 `/produce` (lance-ray) is unauthenticated in-cluster even in prod.** The §1 fix values-gated the
  *gateway* route (`medallion.producer.expose=false`), closing the edge, but the pod still serves the
  route on its ClusterIP and it is NOT sidecar-delivered (so it skips `require_dapr_token`); no
  NetworkPolicy ships. An in-cluster workload can still trigger cascades / forge medallion provenance.
  Fix: a NetworkPolicy restricting `lance-ray:8000`, or an authz guard on `/produce` (it's a real Ray job
  at rask, so this may resolve in the merge — until then the demo default is documented in MEDALLION.md).
  Surfaced by the 9562711 diff review. `services/medallion/api/produce.py`
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
    schema (add_columns evolves it; per-version schemas already ride the WROTE edge). This is also the
    **breaking-change detector**: today a producer renaming/dropping a column a downstream reads is caught only
    at runtime (mover fails → RETRY → stall); declared columns turn that into a pre-promotion contract
    violation. Additive evolution is already safe by construction (immutable versions pin readers).
  - ⛔ P1 **document the data contract** (docs/DATA-CONTRACT.md or an ARCHITECTURE section — currently exists
    only in chat): the bus contract is `{token, dataset, namespace}` + the OpenLineage spec (facet `_schemaURL`s
    ARE the contract); the data contract is "the Lance manifest is the schema, the version is the handshake"
    (self-describing storage, immutable versions, no schema registry needed); enforcement = quality gate
    (promotion-time) + FGA (access-time) + reconcile (drift-time); known gap = breaking changes (see the
    schema-declaration item above); blob columns: inline-vs-pointer semantics are part of the read contract.
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
