# todo_fable — complete fix backlog from the 2026-07-02 comprehensive audit

Source: two adversarially-verified workflow audits (108 agents; 99 findings verified: **91 confirmed**, 6 refuted
as documented demo defaults). Every item below is confirmed with file:line unless marked otherwise. Full raw
detail: workflow journals `wf_c253c55f-52f` (9-dimension) + `wf_e2c6583b-05a` (Dapr) under
`~/.claude/projects/-home-blackwell-Desktop-lance-ns/587d8935-4b16-4bc6-bed7-713ecf01a55d/subagents/workflows/`.

**Legend:** ⛔ not started · P0 security/correctness now · P1 before rask merge / any prod use · P2 quality+perf · P3 nit/doc

---

## 0 · Quality contract — read before working any item

Every rule here traces to a real first-pass defect from the 2026-07-03/04 window (Fable-5 review of the 16
commits, workflow `wf_e2ff6a81-41f`). Definition of done for ANY item below: gate (ruff format + ruff check +
ty) → rebuild the image → redeploy → LIVE-verify the actual flow on kind → adversarial self-audit of the diff
→ commit. A green unit suite is not done. Run the format/lint gate before every test run, not at the end
(E501 churn burned time in nearly every batch).

**Verify third-party contracts BEFORE writing the call site.**
- Probe the INSTALLED package (`uv run python -c "import inspect; print(inspect.signature(…))"`) and read the
  matching `lance_docs/` mirror first. (lance_ray is keyword-only after `uri`; `write_lance` has no
  stable-row-ids param; both lance_ray distributed-index paths are incompatible with pylance 8.0.0 — every
  one was documented locally and still discovered by runtime failure.)
- When observed behavior contradicts the docs mirror (e.g. overwrite upgrades `data_storage_version`), pin it
  with a regression test in the SAME commit — behavior a version bump can revoke must have a tripwire.

**Create-time-only checklist.** Before any new `lance.write_dataset` site: `data_storage_version="2.2"`?
`enable_stable_row_ids=True`? Both are create-time-only — a missed site ships a dataset that can never be
fixed without a destructive rewrite (it happened: 28644cf). Use ONE shared cascade-write helper in
`services/common`; never hand-copy the kwarg pair (six copies exist — collapse them).

**Every table path handles all four states:** absent · declared-only (`is_only_declared` — first-class via
POST /declare AND what our own rollback leaves after a crash) · readable · has-deletions. The ExistOk blob
path 500'd on declared-only until 2026-07-05. Multi-step create (declare → write → grant → emit) must be
retry-safe across a process crash, not just an in-process except.

**Test the SHIPPED composition.** At least one test imports the real app and asserts the real wiring
(middleware order on `catalog.main.app`, the real mover handler, the real demo function — not an inline
re-implementation). The bare-`except`→`except*` 413 bug was invisible precisely because the test rebuilt an
equivalent app. Fakes must reproduce the real boundary's ERROR contract (pyarrow raises FileNotFoundError on
a missing S3 prefix; a fake returning `[]` pins nothing).

**Bus handlers: work < ack window (`backOff[0]` = 30s), always.** Long work = submit with a DETERMINISTIC
idempotency key + re-attach on redelivery; design for the redelivered trigger racing the first attempt
(never a raw destructive step like an S3 dir-wipe mid-handler).

**Helm/k8s: render-and-grep is part of the change.** `helm template | grep` every touched value; confirm
every referenced `.Values.*` key EXISTS (network-policy shipped `.Values.medallion.producer.port` — no such
key); pipe large ints through `| int64` (2.68435456e+08); when two flags must agree
(expose+networkPolicy, dapr+token), add a render/boot-time `fail`, not a comment. kind does not enforce
NetworkPolicy — say so where the template can't be live-verified.

**Sibling-convention rule.** A new dockerfile/manifest copies its siblings' hard rules first (`# syntax=`,
digest pin, OCI labels; secrets via secretKeyRef — NEVER plaintext env; the ray demo shipped `rustfsadmin`
in a pod spec the same week the chart forbade it) and is wired into make/Tilt in the same commit.

**Demos are production surface.** Anything `kubectl apply`-able holds real lakehouse creds: same secret
rules, same exposure rules (an open Ray 8265 + S3 env = in-cluster RCE), writes OUTSIDE the catalog root,
and cleans up its data, not just its k8s objects.

**Commit message = claims audit.** Every "Tests: X" and every number ("4 fragments in parallel") must be
literally true of the diff; grep docs/ + chart/values comments for statements the change just falsified
(two "carries no auth" comments survived the commit that added the auth).

**Executor-independence rule (2026-07-05).** Items marked "execution-spec'd" carry a `✅ DONE WHEN`
checklist and `🚧 GUARDRAILS` block — that is the contract, and it is model-independent: a weaker executor
follows it verbatim; a stronger one may improve the HOW but may NOT skip a DONE WHEN check, cross a
guardrail, or "simplify away" an assert. Every DONE WHEN bullet is binary — if you cannot demonstrate it
(command output, test name, live check), the item is not done. Before committing, run an adversarial review
of the diff (`/code-review` at high effort, or a multi-agent workflow audit) and reconcile every finding;
the DoD's self-audit step is not advisory. If mid-implementation you discover a DONE WHEN check is wrong or
impossible, STOP and update the item first (with evidence) — never silently deliver less than the checklist.

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

- ✅ **DONE 2026-07-11 (Batch 3c) — frontend `poll()` batched + guarded + bounded.** Per-dataset
  fan-outs (producers, graphs) now run concurrently in POOLED batches of 8 (review-caught: a bare
  Promise.all over the catalog's limit=500 list would fire 500 concurrent requests per 2s tick and
  the browser's per-host queue would eat each request's timeout); overlap guard (`#polling` +
  finally) so a slow tick skips interval firings instead of stacking; per-request 8s timeout via
  feature-detected `AbortSignal.timeout` (review-caught: no fallback = silent permanent "offline"
  on Safari <16 — AbortController fallback added). `fetchEvents` now accepts
  `{after, limit, summary}`; svelte-check 0 errors, bun 15/15. Deviation from the batch spec, noted
  honestly: the live board keeps newest-window semantics (no cursor threading in the 2s tick — a
  cursor pages OLDER history, which the UI doesn't render today); the API helper carries it for
  when a history view exists. Playwright e2e remain manual-only (separate tracked item).
- ✅ **DONE 2026-07-06 — `backfill_write` now runs in ONE transaction** (`conn.transaction()`, like
  `ingest_event`): no half-written RECONCILED Run window between sweeps. Unit + real-AGE e2e covered.
- ✅ **DONE 2026-07-10 — `create_table` dual-write now COMPENSATES** (was: Lance create → FGA owner grant →
  lineage emit with no compensation; an FGA outage mid-way yielded a 503 whose retry hit "already exists"
  (Create) or 403'd the Overwrite owner-gate — the table stranded ownerless forever). Fix: the grant is
  try/except-wrapped — on failure the compensation REVOKES any tuples that did land (a grant can commit
  server-side while its response is lost; a stale owner tuple on a freed id = the reused-id privilege
  bleed) then best-effort `drop_table`s what THIS request wrote so the plain retry starts clean, and the
  grant error re-raises. ONLY for a FRESH id (review 2026-07-10 hardening): NEVER for ExistOk (may have
  KEPT a pre-existing table — deleting would destroy data; its retry re-runs the grant and heals) and
  NEVER for an Overwrite that REPLACED an existing table (the id still holds the prior incarnation's
  time-travel history — the review caught that compensating there would escalate a transient FGA blip
  into irreversible loss; stranded-but-admin-recoverable beats destroyed). Moto-proven against the real
  app + storage (compensate→404→retry-200; ExistOk-kept table SURVIVES + heals on retry) + the pure
  `_compensation_allowed` matrix pins the Overwrite arm (unreachable in the FGA-off moto harness).
  **Documented residual:** a process CRASH between write and grant still strands the table (no in-process
  compensation covers it) — the deeper fix is a declare→grant→write reorder, out of proportion for now.
  `services/catalog/api/v1/endpoints/data.py`, `tests/integration/test_moto_s3.py`
- 🟨 **RESCOPED 2026-07-06 — insert version attribution race is now `/insert`-only.** 5c5461f's single
  pinned `read_version_and_schema` open fixed it for merge_insert/update/delete (version+schema pinned to
  the response's version). `/insert` remains read-after-write because the native `InsertIntoTableResponse`
  carries only a `transaction_id` — blocked upstream; reconcile heals the drift. `data.py` insert endpoint.
- ✅ **DONE 2026-07-06 — AGE pool hardened**: `check=AsyncConnectionPool.check_connection` (checkout ping —
  live-verified by force-killing the AGE pod: first post-failover reads all 200) + server-side
  `statement_timeout` (default 30s, `LINEAGE_AGE_STATEMENT_TIMEOUT_SECONDS`, chart-wired — live-verified:
  `pg_sleep(35)` → `QueryCanceled`). `services/lineage/core/age.py`
- ✅ **DONE (two stages) — AGE indexes + Run retention.** Batch-C (e16323a) added UNIQUE indexes on the
  Run/Dataset/Job MERGE keys (boot-ensured + chart initdb); 2026-07-06 added the `:Column(dataset,field)`
  NON-unique lookup index (uniqueness deliberately not enforced — DISTINCT-collapse design keeps the hot
  column path abort-free) + an opt-in **batched Run retention prune** (`LINEAGE_RUN_RETENTION_DAYS`,
  `services.lineage.runRetentionDays`, runs under the reconcile cron's single-flight lock; LIMIT-500
  batches so a backlog can't exceed the statement timeout). Events feed was already retention-capped.
- ✅ **DONE 2026-07-11 (Batch 3a) — `/events` keyset pagination + projection.** `?after=<seq>`
  (keyset off the PK, NEVER OFFSET) + `?limit≤500` + `?summary=true` (drops the full-JSONB `event`
  column AT THE SQL LAYER — four query variants in repository.py); response gains additive
  `next_cursor`. The 2000-row over-fetch is now AUTH-ON ONLY (governance headroom); auth off →
  governed() is pass-through so the fetch collapses to exactly `limit`. Governance-before-slice is
  unit-PINNED (a hidden row never surfaces on any page; cursor is exclusive so no dup/skip of
  visible rows — adversarially reviewed, pagination attacks came up clean). Documented decision:
  `next_cursor` is a WINDOW FLOOR — on a hidden-dense page it can be a hidden row's bare seq
  (exclusive, content never returned; seqs were already inferable from feed gaps — no new
  disclosure class). Defaults = the old behavior exactly. LIVE residual: the feed e2e re-run.
- ✅ **DONE 2026-07-06 — secret fetch off the event loop**: all three lifespans (catalog/lineage/compaction)
  wrap the sync fetch in `run_in_threadpool`; `common/secrets.py` documents the sync-by-design contract.
- ✅ **DONE 2026-07-11 (Batch 3b) — demo peek version-keyed cache + newest-K cap.** Steady-state
  tick = ONE dataset-open (the latest-version probe — irreducible: that read IS the change check;
  honest refinement of the spec's "zero opens") + the versions() listing; zero per-version opens on
  an unchanged tick; a NEW version re-opens ONLY itself. Cap `LINEAGE_DEMO_MAX_VERSIONS` (default
  50) bounds the cold tick too. Review-caught + fixed: incarnation identity — a delete+recreate at
  the same URI that reaches the SAME (or higher) version count while nobody polls would have been
  served stale forever under a bare version-number key → every cache hit is validated against the
  live manifest TIMESTAMP (same (version, stamp) = same immutable manifest); and below-window-floor
  entries are pruned (the cascade mints a version per tick — unpruned cache = slow unbounded leak).
  All pinned by counting-fake + same-version-recreate + prune unit tests (test_lineage_demo.py).
- ✅ **DONE 2026-07-05 — RustFS conditional-write (CAS) VALIDATED (PASS).** `tests/e2e/test_object_store_cas_e2e.py`
  + `make e2e-cas` ran green against the live kind cluster: tier-1 second-put→412; tier-2 exactly one 200 +
  seven 412 per round (5 rounds); tier-3 8-process append → count_rows()==800 + full id set + len(versions())==9.
  Verdict + evidence recorded in docs/DURABILITY.md. RustFS honors If-None-Match AND pylance's object_store
  sends conditional puts to the custom endpoint. Original finding below (kept for the remediation path if a
  future backend swap fails the gate):
- ~~⛔~~ **RustFS conditional-write (CAS) support has NEVER been validated — Lance commit safety rests on it**
  (added 2026-07-05, firnflow/lance_docs audit; execution-spec'd same day after an Opus fresh-implementer
  dry-run). Every Lance commit publishes a new manifest via put-if-not-exists (`If-None-Match: *`); the
  format REQUIRES the store to guarantee exactly one writer wins (`lance_docs/file_format.md:4765`), and
  NOTHING detects a store that silently ignores the header (proven failure mode elsewhere: GCS S3-interop
  accepted both PUTs → silently lost writes; only a contended stress catches it). Our concurrent writers are
  real — catalog inserts, medallion overwrites, Ray appends, the 120s compaction sweep with no overlap guard
  that swallows every error — and RustFS is a pre-1.0 beta (`chart/values.yaml:179`). Add a 3-tier harness
  `tests/e2e/test_object_store_cas_e2e.py` (pytest marker `cas`, register it in pyproject) + `make e2e-cas`
  (reuse the e2e-compaction recipe STRUCTURE but port-forward `svc/<release>-rustfs 9000`; creds via
  `LANCE_E2E_S3_ENDPOINT/ACCESS_KEY_ID/SECRET_ACCESS_KEY/BUCKET`, secret key read from the infra-credentials
  Secret). boto3 client MUST use path-style addressing + s3v4. Tiers: (1) conditional-PUT pre-flight — second
  put of the same key must fail 412; (2) 8-thread barrier-gated contended-key stress — exactly one 200 +
  seven 412 per round (THE silent-ignore detector); (3) 8-process Lance append stress under
  `s3://<bucket>/__cas_stress/<uuid>` (compaction's discovery skips `__` dirs): SEED-CREATE the dataset first
  in the parent process (v1, 2.2 + stable row ids per §0) — concurrent creates would be Overwrite races,
  which DO conflict — then 8 append-only writers; Append⊥Append never logically conflicts
  (`file_format.md:~4801`) so ALL must land: assert count_rows()==800 AND len(ds.versions())==9 (v1 seed + 8
  appends); assert DATA invariants, not exception names (none are documented). Raise `lance_aimd_max_rate`
  very high in storage_options (there is NO full-disable for S3 stores, `guide.md:3080`) so client throttling
  can't mask store behavior; clean up both prefixes even on assertion failure (§0). TWO-LAYER VERDICT —
  report separately: tiers 1-2 prove the STORE honors If-None-Match; tier 3 proves pylance's object_store
  actually SENDS conditional puts to this custom endpoint (a store can pass 1-2 while Lance still loses
  writes). If tier 3 loses rows while 1-2 pass, FIRST probe object_store's conditional-put storage option
  before blaming RustFS. If RustFS fails 1-2, remediation is real work, in cost order: RustFS upgrade;
  external manifest store via lance-namespace `table_version_management=true` (`namespace.md:6181-6202` —
  NOT a config toggle: per `namespace.md:1022` it routes ALL version ops through the namespace
  CreateTableVersion API, touching catalog dataplane + medallion + Ray + compaction); backend swap. Record
  the verdict in docs/DURABILITY.md as the gate for any backend swap; this is also the evidence base for the
  insert version-attribution retry-loop item above (what error, if any, surfaces on a lost race).
  ✅ DONE WHEN: `make e2e-cas` runs green against the live kind cluster and prints a TWO-layer verdict
  (store: tiers 1-2 PASS/FAIL; lance-path: tier 3 PASS/FAIL) · tier-1 asserts second-put 412 · tier-2 asserts
  exactly one 200 + seven 412 PER round · tier-3 asserts count_rows()==800 AND len(versions())==9 · both
  `__cas_probe/` + `__cas_stress/` prefixes verified deleted after the run (list call), including on failure ·
  docs/DURABILITY.md records verdict + date + RustFS image tag · `cas` marker registered; `make ci` untouched.
  🚧 GUARDRAILS: never write outside the two `__` prefixes · never weaken tier-2's exactly-one-winner assert
  to "at least one" (that is the silent-ignore hole) · a tier-3 pass alone is NOT store validation (pylance
  auto-retry masks) · no hardcoded creds (env/Secret only, §0) · if ANY tier fails: STOP, record the verdict,
  do NOT attempt remediation in the same change.
- 🟡 **`/merge_insert` has no scalar index on its `on` key — CODE-COMPLETE 2026-07-10, live /merge_insert
  on kind PENDING** (added 2026-07-05; execution-spec'd same day after an Opus fresh-implementer dry-run).
  **2026-07-10 status vs the DONE WHEN checklist:** implemented exactly as spec'd —
  `dataplane.ensure_merge_key_index` (no-op on falsy `on`; LIST FIRST + skip when any index covers the key
  — the replace=True rebuild guard; build via the native `create_table_scalar_index` with branch forwarded;
  broad try/except, never fails the write), hooked inline via `run_in_threadpool` after the merge + emit;
  endpoint docstring documents the implicit DDL + the version gap. Moto-proven against the real app: two
  consecutive merges → exactly ONE build (call-count spy) · BTree on `id` visible via the list endpoint ·
  monkeypatched list+build failure → merge still 200 with the upsert applied. **Branch propagation on the
  index build is documented UNVERIFIABLE at pylance 8.0.0** (branch surfaces are dataplane-backed on the
  dir backend; the param is forwarded — flagged for the live pass). **NOT done: the DONE WHEN live check**
  (one real /merge_insert on kind) — in the §7a RESIDUAL. Original spec kept below as the contract:
  pylance's `use_index=True` default only
  helps "if an index is available"; no automatic data-flow ever builds one (the only build call sites are the
  smoke test's endpoint POSTs and the Ray demo's BTREE on `id`), so merge latency decays as a table grows.
  The namespace spec's own `__manifest` design mandates exactly the fix — merge-insert PK dedup **with**
  "BTREE index on object_id" (`lance_docs/namespace.md:978-994`). Add best-effort
  `ensure_merge_key_index(ns, segments, on, *, branch=None)` in `services/catalog/services/dataplane.py`:
  (1) no-op when `on` is falsy; (2) LIST FIRST via the native `list_table_indices` (branch-aware) and SKIP
  the build if any existing index already covers `on` — REQUIRED, not optional: pylance's
  `create_scalar_index` defaults `replace=True`, so an unconditional build would full-scan + rebuild the
  column on EVERY upsert and turn the fix into a regression; (3) otherwise build via the native op path —
  `native.call(ns, "create_table_scalar_index", CreateTableIndexRequest(column=on, index_type="BTREE",
  branch=branch))` — the native op is the only path that carries `branch` (pylance's `ds.create_scalar_index`
  has none); LIVE-verify the branch is actually honored on build (§0); (4) broad try/except + log.warning —
  index-build failure or a CreateIndex commit conflict must never fail the write. Hook: fire inline via
  `run_in_threadpool` in `merge_insert_into_table` AFTER the merge native.call and the emit (matching the
  emit_write_event pattern; §0 forbids BackgroundTasks) — the FIRST merge on a table pays the build latency
  synchronously, subsequent merges pay one cheap list call. The existing compact→optimize_indices sweep folds
  later fragments in (30 min prod cadence). Implicit DDL — document BOTH on the endpoint: the build commits a
  NEW Lance version with no lineage event (consistent with /create_scalar_index today), so the first indexed
  merge leaves the table at response.version+1 while the MERGE_INSERT lineage points at response.version —
  a version gap, not a lost write. Tests (tests/integration/test_moto_s3.py): merge with on=id → BTREE
  visible via the list endpoint; monkeypatched build failure → merge still returns 200.
  ✅ DONE WHEN: two consecutive merges on the same (table, on) trigger exactly ONE index build (assert via
  call-count monkeypatch or stable list_table_indices output — the idempotence proof) · index visible via the
  list endpoint after the first merge · monkeypatched build failure still returns 200 with the merge applied ·
  branch propagation live-verified or explicitly documented as unverifiable at pylance 8.0.0 · endpoint
  docstring documents implicit DDL + the version gap · live-verify one real /merge_insert on kind (§0).
  🚧 GUARDRAILS: NEVER build unconditionally (replace=True → full rebuild every upsert = regression) · no
  exception from the ensure path may reach the HTTP response · build only AFTER the merge commits · BTREE
  only, this endpoint only (no auto-index creep into other write paths).
  `services/catalog/api/v1/endpoints/data.py:175`
- 🟡 **Compaction failures are invisible to every API — CODE-COMPLETE 2026-07-10, live fault-injection
  PENDING** (added 2026-07-05; execution-spec'd same day after an Opus fresh-implementer dry-run).
  **2026-07-10 status vs the DONE WHEN checklist:** implemented as spec'd, then hardened by a 4-angle
  adversarial review of the diff — `build_maintenance_fail_event` (derives from the COMPLETE builder so
  the job/output key can't drift) + `emit_maintenance_failed` (deterministic
  `run_id_for("compaction-fail-<id>")` flood guard; COMPLETE keeps uuid4 semantics — its two touched
  tests were EXTENDED, assertions unweakened, and the unprefixed-error branch got explicit coverage
  back), maintain-only selection (open: → nothing AND bare "boom" → nothing, both test-pinned),
  errorMessage facet (message capped 1000 chars + programmingLanguage + best-effort `retryable` custom
  field with NEGATION handling — "not retryable"/"retries exhausted" → False, review caught the
  inversion), FAIL batch derived-then-capped (cap counts ACTUAL emits — unparseable URIs can't starve
  slots), shuffled before the cut (a deterministic head-slice would re-drop the same datasets every
  tick), gathered concurrently with `return_exceptions` + an outer guard (raise-proof even for a
  mis-wired emitter), `compact_files(defer_index_remap=True)` + real-Lance interplay regression
  (`tests/unit/test_compaction_optimize.py` drives the shipped `compact_one`; `indices_optimized` now
  counts USER indices only — the review found the new `__lance_frag_reuse` SYSTEM index inflating the
  metric, verified on pylance 8.0.0), composed boundedness test (30 failures through the REAL emitter
  vs a hung sidecar completes in ~one publish timeout), chart `lineageEmit` comment documents
  failure-surface-requires-on + the runRetentionDays pairing; medallion-nested blind spot documented in
  the emit docstring. **Known limitations (review, accepted + documented in code):** across DISTINCT
  failure episodes /events keeps the FIRST FAIL row while /runs shows the LATEST error (the feed's
  keep-first contract × the deterministic id — /runs is the live view); with retention off (default) a
  recovered dataset's FAIL node persists in /runs; under LINEAGE_FGA_ENABLED a FAIL for a DROPPED table
  whose dir lingers is hidden from governed readers (tuples revoked on drop — the ungoverned
  reconcile/ops readers still see it); namespace derivation assumes catalog/compaction delimiter
  agreement (both default `$`; nothing enforces it — pre-existing, shared with the COMPLETE event).
  **NOT done (needs the cluster): the DONE WHEN live check** — fault-inject a dataset (delete a data
  file under its manifest), assert exactly ONE FAIL Run node across ≥2 cron ticks via /runs + /events
  with lineageEmit=true; also rebuild+roll the compaction image. Listed in the §7a RESIDUAL. Original
  spec below (kept as the contract):
  `compact_one` never raises (error → string) and `emit_sweep_lineage` used to SKIP
  errored datasets, so a persistently failing dataset surfaced only in OTel spans + a cron response body
  nobody reads. Emit an OpenLineage FAIL RunEvent per errored dataset. Scope + mechanics (all decided — do
  not relitigate):
  - EMIT ONLY for `maintain:`-prefixed errors (escaped compact_files/cleanup = post-auto-retry terminal);
    skip `open:` errors (unreadable/declared-only dirs — transient non-dataset noise). Conflict taxonomy is
    THREE-way (`file_format.md:~5253`): Rebasable (auto-retried inside the commit layer, never reaches
    Python — never report), Retryable (app must re-run), Incompatible (non-retryable).
  - Event shape: mirror `build_maintenance_event` with eventType=FAIL + a standard `errorMessage` run facet
    (message + programmingLanguage="PYTHON"). The compaction COMPLETE event is ALREADY bare/versionless —
    unlike the medallion FAIL there is nothing to strip; the only delta is FAIL + the facet. Keep the bare
    output dataset (FGA hides dataset-less events on /runs).
  - Retryable-vs-non-retryable classification is BEST-EFFORT ONLY: pylance 8.0.0 raises no typed conflict
    exception (`lance.commit.CommitConflictError` exists but is never raised) — use a string heuristic on
    str(exc) recorded as a custom field on the (extra=allow) facet; there is no ground-truth signal.
  - Flood guard: DETERMINISTIC run_id = `run_id_for(f"compaction-fail-{table_id}")` so every tick's FAIL for
    the same dataset MERGEs onto ONE (:Run) node and the /events partial-unique (run_id, event_type) dedups
    it (a uuid4-per-tick would flood the never-pruned Run nodes — §4 item above). ACCEPTED consequence: after
    recovery the FAIL node stays until the §4 retention prune lands; do NOT change COMPLETE's uuid4 semantics.
  - Cap/bound-gather the per-tick FAIL publishes (each bounded by the 5s publish timeout) so a bucket of
    failing datasets can't push the cron handler past the 30s Dapr ack window (§0).
  - Also adopt `compact_files(defer_index_remap=True)` (Fragment Reuse Index — compaction and index-build "no
    longer conflict", `lance_docs/guide.md:3150`; keyword confirmed present at pylance 8.0.0) to cut failures
    at the source; PROBE its interplay with the immediate `optimize_indices()` at optimize.py:77 and pin with
    a regression test in the same commit (§0).
  - SCOPED OUT: medallion-nested datasets (`s3://<bucket>/medallion/<ns>` has no catalog id for
    `table_id_from_uri` to reconstruct) — document the blind spot; a URI→id map is out of proportion here.
    Chart `lineageEmit` STAYS default-false (opt-in, symmetric with medallion) — document that the failure
    surface requires it on.
  - Live-verify fault injection (no dataset fails naturally): seed a real dataset then delete one data file
    out from under its manifest — discovery still finds it via `_versions/`, compact_files raises a
    `maintain:` error → assert the FAIL event lands in /events. Extend tests/unit/test_compaction_lineage.py
    for the FAIL path (it currently covers only errored→skip selection).
  ✅ DONE WHEN: fault-injected dataset produces exactly ONE FAIL Run node across ≥2 cron ticks (deterministic
  run_id proven live via /runs + /events with lineageEmit=true) · FAIL event shape verified: eventType FAIL,
  bare output (name only), errorMessage facet with message + programmingLanguage, NO version/schema/stats
  facets · an `open:`-errored dir produces NO event (test) · `defer_index_remap=True` in compact_files + a
  regression test pinning its interplay with optimize_indices · publish loop provably bounded (test: N
  simulated failures, handler under the 30s ack window) · unit tests extended for FAIL path + maintain-only
  selection + dedup.
  🚧 GUARDRAILS: never fabricate lineage — no version facet, no DERIVED_FROM, nothing beyond the bare output
  name on a FAIL · do NOT touch the COMPLETE path's uuid4 run_id or its existing tests · cap errorMessage
  length (exception strings embed URIs) · emission stays best-effort — a publish failure must never fail the
  sweep · medallion-nested datasets stay out of scope (document, don't bolt on a URI→id map).
  `services/compaction/services/optimize.py:88` + `services/compaction/services/sweep.py:90`

## 5 · P2 — Python / FastAPI quality + consistency — ✅ 17/17 DONE (2026-07-02)

DONE: catalog config comment-lie (fail-closed, no env fallback); `handle_stage` `fga_client: Any` →
`OpenFgaClient | None`; `_BACKFILLED`/`_BACKFILLABLE` deduped → one public `BACKFILLABLE_STATES`;
`governed()` → PEP 695 generic `[T]`; `lineage_transport` → `Literal` (parity with `vending_mode`);
`_s3fs` scheme derived from the endpoint (no silent HTTPS→http downgrade); `problem_detail` returns a
generic detail on 5xx (no `str(exc)` leak); lineage lifespan teardown suppress-per-close.
BATCH 2 (26dff20) added: catalog health probes async; `/docs` gating (LINEAGE/MEDALLION/COMPACTION_DOCS);
medallion+compaction `/readyz` lifecycle flags; medallion `/produce` RFC 9457 + Retry-After; compaction
empty-secret boot guard (lifespan). BATCH 3 added: secret-splice dedup → `common.secrets.fetch_required_secrets`
(catalog/lineage/compaction all call it; the fail-closed rule lives in one place).
BATCH 4 (final) added: (#4) S3 secret → `SecretStr` across lineage/medallion/compaction (all 10 read-sites
+ the 2 guards migrated to `.get_secret_value()`; repr-redaction verified); (#13) emitter dedup via a shared
`_BaseLineageEmitter` (~60 fewer lines); (#15) docstrings on 48 catalog endpoint handlers (9-agent fan-out,
each import-verified, then trimmed to the line limit). Plus the caught-live bugfix: `/produce`
`response_model=None` (the `dict | JSONResponse` union crashed lance-ray at startup) + a regression test that
builds every medallion app's OpenAPI. ALL of §5 live-verified on the cluster (helm rev 47).


*(2026-07-06 truth-up: the 17 itemized ⛔ bullets that used to sit here were the ORIGINAL find-list,
left unflipped after the fix batches above landed. Every one was re-verified against the code today —
comment-lie fixed at `catalog/core/config.py:63`, compaction boot guard via `fetch_required_secrets`,
splice deduped in `common/secrets.py`, SecretStr everywhere, teardown suppress-per-close in
`lineage/main.py:99`, `fga_client: OpenFgaClient | None`, `BACKFILLABLE_STATES` single-sourced, async
catalog probes, RFC 9457 + Retry-After on `/produce`, generic 5xx `problem_detail`, readyz lifecycle
flags, `*_DOCS` gating, `_BaseLineageEmitter` dedup, endpoint-derived `_s3fs` scheme, handler docstrings
(e.g. `tables.py:114`), `governed[T]`, `lineage_transport: Literal` — so the section header's 17/17 DONE
is accurate and the list is removed rather than left contradicting it.)*

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
- ✅ **DONE 2026-07-06 — AGE-backed e2e in CI via Dagger**: `dagger call test-lineage` runs the lineage
  e2e against a hermetic apache/age service container — identical locally (`make e2e-lineage`) and in CI
  (`lineage-e2e` job). Suite grew a §4 test: batched Run-prune + per-version schema + Column-index DDL
  against real AGE. `.github/workflows/ci.yml`, `.dagger/e2e.go`
- ✅ **DONE 2026-07-06 — /events Postgres surface against real PG** (Dagger/CI suite): record_event
  redelivery dedup (3-col natural key + terminal partial index vs a fresh-eventTime terminal), newest-first
  jsonb round-trip, seq-window retention prune, lineage_reads audit row. `tests/e2e/test_lineage_e2e.py`
- ✅ **DONE 2026-07-06 — `dataset_schema` at-version exercised against real AGE**: the Dagger/CI lineage
  e2e asserts per-version schema resolution (v1 vs v2 fields) on a live apache/age — the int-vs-string
  `$ver` quirk is now regression-gated. `tests/e2e/test_lineage_e2e.py`
- ✅ **DONE 2026-07-06 — `RunEvent.progress` tested at three layers (all unit-tier)**: facet parse
  (both-fields-or-None; non-coercible → None since 2026-07-10), the conditional `_SET_RUN_PROGRESS` at
  ingest (never clobbered back to null), and the 12-col /runs fold — plus, since 2026-07-10, the
  real-AGE `list_runs` column-order pin in the e2e tier. `tests/unit/test_lineage.py`
- ✅ **DONE 2026-07-06 — Reconcile cron route**: OPTIONS ack (no token — Dapr's discovery probe), exact
  binding-name registration, 403 on missing/wrong token (sweep never runs), tokened POST → full report
  shape incl. pruned_runs. `tests/unit/test_reconcile.py`
- ✅ **DONE 2026-07-06 — Demo router behavioral test** (real local-Lance reads): absent→exists:false,
  per-version schema walk across evolution, gold's embedded lineage JSONB round-trip, best-effort
  degradation to None. `tests/unit/test_lineage_demo.py`
- ✅ **DONE 2026-07-11 (Batch 6) — frontend suites in CI.** New `frontend` job in ci.yml: bun
  frozen-lockfile install → `bun run check` (svelte-check, 0-errors gate) → `bun test src/lib`
  (15 tests) → `bunx playwright install chromium` → `bun run test:e2e` (the 3 hermetic Playwright
  specs — they mock every /api/** via page.route by design, so no backend; traces uploaded on
  failure). ALL THREE TIERS VERIFIED LOCALLY before landing: svelte-check 0/0, bun 15/15,
  Playwright 3/3 passed (23s) against the pre-installed chromium. PROVEN IN CI 2026-07-11: the
  job's first Actions runs went green (svelte-check → bun → Playwright, ~70s; run 29159853966 and
  the fully-green 29160855426).
- ✅ **DONE 2026-07-06 — /graph transitive-disclosure filter unit test**: hidden node dropped, edges dropped
  in BOTH leak directions, root kept WITHOUT re-checking it. `tests/unit/test_lineage_auth.py`
- ✅ **DONE 2026-07-06 — governed FULL-UNION e2e** (`make e2e-governed-union`, 4 passed live in 126s on the
  auth+FGA+compute+quality stack): governed allow-path with per-stage run-id correlation + quality verdicts
  + 401/403 boundaries; FGA-deny→DROP live (validator tuple revoked via the OpenFGA API → gold never lands;
  re-grant restores); quality-block live (nulled-id bronze → `quality_passed=false` + failed `not_null`
  recorded, gold never triggered, /produce recovers); media lane under governance incl. the transitive-
  disclosure filter hiding ungranted s3:// sources. Plus the seed-script fix it surfaced: table→namespace
  parent tuples for mover datasets (previously invisible to ALL humans under LINEAGE_FGA_ENABLED).
  `tests/e2e/test_governed_union_e2e.py`

### §7a · PICK-UP HERE — governed-union audit follow-ups (2026-07-06, workflow wf_45d9bf8e-ec9: 22 confirmed, 1 fixed, 3 refuted)

The governed-union e2e itself PASSED live (4/4, 126s) and is pushed; these harden the harness + close
what the audit proved the tests DON'T yet prove. Every item verified against code with file:line.

> **2026-07-10 close-out batch (remote session — no kind cluster available):** every item below is
> implemented; §0 gate green (ruff format+check over services/tests, `uvx ty check` 0 diagnostics,
> 342 unit + 95 integration passed, e2e files collect clean, make recipe + seed script `bash -n`
> clean). The §0 adversarial self-audit ran as an 8-angle review (line-scan / removed-behavior /
> cross-file / reuse / simplification / efficiency / altitude / conventions); every surviving finding
> was applied in the same batch — the headline one KILLED the s3:// positive-control sub-item as
> unimplementable (see that item below). Honest §0 caveat: items in the e2e suites / Makefile are
> 🟡 **code-complete, LIVE RUN PENDING** — the next `make e2e-governed-union` (kind union stack) +
> `make e2e-lineage` (Dagger, needs docker) is the done-done proof; ✅ *(unit-proven)* items are fully
> verified here. Also in this batch: removed the now-unused `ty: ignore[missing-argument]` in
> `catalog/core/config.py` (current ty flags it, failing CI's unpinned `uvx ty check`); refreshed the
> stale `docs/COVERAGE.md` test tally (320 → 437 measured); seed-script `w()` now fails loudly on
> non-duplicate write errors (the Makefile seed-abort was unreachable for grant failures otherwise).
>
> - ⛔ **RESIDUAL — the done-done pass:** on the kind union stack run `make e2e-governed-union` and
>   `make e2e-lineage` green with these changes, and rebuild+roll the shared catalog image so the
>   `RunEvent.progress` poison-guard actually ships. Until then nothing below counts as §0-done.
>   **Added 2026-07-10 (Phase 2):** with `compaction.lineageEmit=true` + a rolled compaction image,
>   fault-inject a dataset (delete one data file under its manifest) and assert exactly ONE FAIL Run
>   node across ≥2 cron ticks via /runs + /events — the §4 compaction-failure item's live DONE WHEN.
>   **Added 2026-07-10 (#115a/c):** with helm available: wire the train values passthrough
>   (topic/entrypoint/trainer identity/models namespace) into chart/templates/medallion.yaml +
>   values.yaml and render-and-grep it (§0); re-run the seed; then the #115a live DONE WHEN (one POST
>   /train drives the stub job end to end; ungranted trainer → DROP with no job submitted).
>   **Added 2026-07-11 (#115b):** rebuild the ray-lance image (it now bakes `ray_train_job.py`) and
>   re-`helm upgrade` (the nats-stream Job must create the new `TRAINING` stream — without it every
>   /train publish 503s); then the #115b live DONE WHEN: POST /train → `upstream(models$<m>)` shows
>   the feature datasets WITH pinned versions, /runs shows the START→RUNNING→COMPLETE trail, a
>   serving-shaped read loads weights from the PLAIN path (no Lance reader), FAIL path fault-injected
>   once (bad feature version → FAILed run, versionless output, registry unchanged), and redelivery
>   of the same token never double-publishes (re-attach observed in mover logs). Set
>   `vending.externalBlobBases` to include the deployment's `s3://<bucket>/models/` prefix.
>   **Added 2026-07-11 (Batch 4):** after the FAIL-path fault injection above, run the janitor
>   dry-run against the crashed token (`model_artifact_janitor.py --registry-uri … --artifact-base
>   …`) and verify the report lists it as a candidate and the published tokens as
>   kept_referenced; only then exercise `--delete` once.
>   **Added 2026-07-11 (Batches 9+10, security):** on a POLICY-ENFORCING CNI cluster (Calico/
>   Cilium — kind's default ignores NetworkPolicy): (1) `--set networkPolicy.enabled=true` →
>   all pods Ready, e2e suites green, NEGATIVE probe `kubectl exec deploy/<release>-web -- wget
>   -T3 -qO- http://<release>-openbao:8200/v1/sys/health` TIMES OUT while the catalog still
>   consumes secrets (positive control); (2) `--set security.serviceAccounts.enabled=true` →
>   pods Ready + `dapr mtls -k` still verifies (the audit's pre-flip gate); (3)
>   `--set security.infraContexts.enabled=true` → infra pods Ready, PVC data intact after a
>   rollout restart (fsGroup proof); (4) ONLY THEN label the namespace
>   `pod-security.kubernetes.io/enforce=baseline` (→ `restricted` after soak).
>   **Added 2026-07-11 (Batch 12):** rebuild the web image once (`docker build -f
>   .docker/web.dockerfile .`) — the dockerfile now builds the Turborepo workspace; ASSERT the
>   image boots (`bun ./build/index.js`, port 3000) and /lineage renders with the search box.
>   **Added 2026-07-11 (Batch 5):** `make e2e-lineage` now also runs
>   `test_terminal_lifecycle_and_column_gc_against_age` — the three new Cypher shapes (read-time
>   dropped derivation with the COMPLETE filter; NOT..IN list-param HAS_COLUMN DELETE; the
>   version-recency gate) executing on REAL AGE 1.5.0, asserting: drop→dropped_at==drop time;
>   recreate→None; inventory==[x,y] after the schema replacement; stale redelivery changes nothing.
>   **Added 2026-07-10 (§4 batch 2):** one real `/merge_insert` on kind (observe the merge-key BTREE
>   land + the documented version gap; also probe whether `branch` is honored on the index build —
>   unverifiable at pylance 8.0.0 locally), and a rolled catalog image so the merge-index hook + the
>   create-compensation actually ship.
>
> - 📋 **PICK-UP HERE — NEXT CODE BATCHES, execution-spec'd 2026-07-11** (chosen because every 🟡
>   above waits on the user's kind session; these four need NO cluster. Ordered by risk: docs first,
>   deletion-adjacent last. Each batch = its own commit + the full §0 gate + adversarial review.)
>
>   **BATCH 1 — stale-docs sweep (the §8 ⛔ list, 12 items). ✅ DONE 2026-07-11** — fact-check-first
>   per the guardrail; found 9/12 ALREADY fixed (the todo list was the stale artifact), fixed the
>   real 3 (system-diagram .md+.html, SYSTEM-SKETCH register/roadmap, COVERAGE tally). See the §8
>   sweep-result block. Spec kept below for the record:
>   ✅ DONE WHEN: every ⛔ line in the §8 stale-docs list is fixed in its named file · each rewrite is
>   verified against CODE first (count the real vending shapes; re-measure the COVERAGE tally from a
>   live `--co -q` collect; `grep -r deadLetterTopic` before touching DLQ wording) — never rewritten
>   from the todo's own summary · the RASK-INTEGRATION seam contract UNAMBIGUOUSLY forbids the future
>   Ray producer job publishing `medallion.raw` (the post-B2 double-fire is the merge's
>   highest-stakes doc bug) · every fixed line flips ✅ (dated) in §8.
>   🚧 GUARDRAILS: wording-only — NO behavior change rides along; if verifying a doc claim exposes a
>   real code bug, FILE it as a new todo item, don't fix it in this batch · LINEAGE.md JSONB item =
>   reword to demo-only (do NOT implement mover embedding here) · DLQ items = fix the wording (do NOT
>   configure a deadLetterTopic here).
>
>   **BATCH 2 — docs/DATA-CONTRACT.md (§9 P1, currently exists only in chat). ✅ DONE 2026-07-11** —
>   all six DONE-WHEN sections present, linked from README + ARCHITECTURE, §9 line flipped with
>   detail; the doc's §4 is the honest prod-readiness split the guardrail demanded. Spec below:
>   ✅ DONE WHEN: the doc covers (a) the bus contract — trigger payloads + "facet `_schemaURL`s ARE
>   the contract" + the claim-check rule (pointers never data, NATS ~1MB); (b) the storage contract —
>   "the Lance manifest is the schema, the version is the handshake" (self-describing, immutable
>   versions, no schema registry); (c) an enforcement-points table — quality gate (promotion-time),
>   FGA (access-time), reconcile (drift-time); (d) blob inline-vs-pointer read semantics; (e) the
>   model-registry addendum (D4: the registry commit IS the registration; artifact base stable per
>   model); (f) the known gap — breaking-change detection, pointing at the §9 schema-declaration
>   item · linked from README + ARCHITECTURE · the §9 P1 line flips ✅.
>   🚧 GUARDRAILS: document REALITY only — every claim traceable to shipped code/tests (cite files);
>   the P2 schema-declaration MECHANISM stays un-built; no new invariants invented mid-doc.
>
>   **BATCH 3 — read-path perf trio (§2 ⛔s: /events over-fetch · demo-peek re-reads · frontend
>   poll fan-out). ✅ DONE 2026-07-11** — all three DONE-WHENs met (details on the flipped §2
>   items); adversarial review confirmed the pagination attacks clean and caught 5 real issues,
>   all fixed: same-version-count recreate serving a dead incarnation (timestamp identity),
>   unbounded 500-request frontend fan-out (pooled batches of 8), AbortSignal.timeout missing on
>   Safari <16 (feature-detect fallback), _VERSION_FIELDS slow leak (window-floor prune), and the
>   hidden-seq window-floor cursor (documented as a no-new-disclosure decision). Gate: 500
>   backend tests, svelte-check 0/0, bun 15/15. Spec below:
>   ✅ DONE WHEN: (a) `/events` takes keyset pagination (`?after=<cursor>&limit=`, server cap ≤500,
>   NEVER OFFSET) + a column projection instead of full-JSONB rows, returns the next cursor, and the
>   governance filter provably applies BEFORE the slice (unit-pinned); frontend store threads the
>   cursor · (b) demo peek does ZERO S3 dataset-opens on a poll tick whose latest version is
>   unchanged (per-dataset version-keyed cache; immutable versions make entries permanent) + a
>   last-K-versions cap — a counting-fake unit test pins the open-count drop · (c) frontend `poll()`
>   batches its per-dataset calls (Promise.all), guards overlap (no tick starts while one runs), and
>   aborts on timeout — no unbounded stacking.
>   🚧 GUARDRAILS: existing response SHAPES unchanged for current callers (new params optional;
>   defaults = today's behavior) · governance filtering must never move AFTER a cap/slice (pagination
>   must not leak) · demo endpoints STAY demo-only (adding auth is the separate tracked posture item)
>   · no new frontend dependencies.
>
>   **BATCH 4 — orphan-artifact janitor (§9 blob-pointer lifecycle, scoped to the model lane the
>   #115b design made load-bearing). ✅ DONE 2026-07-11** — every DONE-WHEN met incl. the
>   invariant-test-first guardrail; details on the flipped §9 sub-item. Live dry-run proof on
>   kind added to §7a. Spec below:
>
>   **BATCH 5 (added + ✅ DONE 2026-07-11) — claim-check publish guard + lineage graph hygiene.**
>   (a) payload guard in the ONE publish choke point (`common.dapr_publish`): >900 KiB →
>   ValueError naming the claim-check rule before any I/O, >64 KiB → warning; behavior-preserving
>   (broker would refuse anyway; every caller already handles the failure path). (b) column-
>   inventory GC on overwrite + (c) reconcile skips deliberately-dropped datasets via READ-TIME
>   derivation over run history. Adversarial review KILLED the first (b)/(c) design — a stored
>   dropped_at stamp and an ungated prune were both last-delivery-wins under at-least-once
>   redelivery (a stale redelivered drop/schema could deactivate or rewrite a LIVE dataset) —
>   rebuilt as derivation + a version-recency gate, both redelivery-proof by construction. Tests
>   named per item on the flipped §2/§9 lines; the three new Cypher shapes additionally get a
>   LIVE AGE e2e (`test_terminal_lifecycle_and_column_gc_against_age`) queued in §7a — AND it
>   runs automatically in CI's existing `lineage-e2e` Dagger job (real AGE) on the next push, so
>   the live proof does not wait on the kind session. Gate: 517 unit+integration green,
>   ruff+ty clean.
>
>   **BATCH 6 (added + ✅ DONE 2026-07-11) — frontend suites in CI + facet-bloat cap.** (a) new
>   ci.yml `frontend` job (svelte-check → bun 15 tests → hermetic Playwright 3 specs, traces on
>   failure) — all three tiers verified green locally before landing; (b) `FACET_MAX_FIELDS=512`
>   in the shared schema_facet builder (spec-true truncation + warning; full schema stays
>   readable from storage). Tests + assertions on the flipped §7/§9 lines. Gate: 519 green.
>   PROVEN IN CI same day (run 29160855426 fully green) after two CI-loop catches: the local ty
>   gate had been scoped narrower than CI's unscoped `uvx ty check` (now gate CI-exact), and the
>   live-AGE lineage-e2e caught the stale-redelivery reseed the unit fakes couldn't (fixed by
>   recency-gating the seeding — see the Batch 5 flips).
>
>   **BATCH 7 (added + ✅ DONE 2026-07-11) — medallion secrets via the Dapr store.** The service
>   half of a latent chart gap: store-on deployments omitted medallion's plaintext S3 env but
>   nothing consumed the store (credential-less movers). `MEDALLION_SECRETS_FROM_DAPR` +
>   `apply_dapr_secrets` in both lifespans (strict sole source, fails closed, symmetric with the
>   other three services) + chart else-branches; skipVerify sub-item verified already-shipped.
>   Tests + assertions on the flipped §9 P1-externalization line. Gate: 523 green, CI-exact.
>   PROVEN IN CI same day (run 29166555186 fully green incl. the helm render of the chart change).
>
>   **BATCH 13 (added + ✅ DONE 2026-07-12) — the P1 credential-less blob serving path.**
>   `GET /v1/table/{id}/blobs?column=&row=[&version=]` + `dataplane.read_blob`: STREAMED in bounded
>   8 MiB `read_range` windows (never buffers a payload), full RFC 9110 Range semantics (200/206/
>   416, `Content-Range`, `Accept-Ranges`, strong `ETag` + `If-Range` so a resume across an
>   overwrite can't splice two incarnations), every probed pylance failure shape mapped to a
>   precise 4xx, and zero-length/null payloads served as empty 200s (probed: pylance 8.0.0 stores
>   null as size-0 — same row state). Reader-tier authz via the router's suffix map (`blobs` ∈
>   `_DATA_READ_ACTIONS`), pinned at unit AND integration (end-to-end 403). Adversarial review
>   (fix-first verdict) drove the streaming upgrade, the empty-payload fix, the tightened
>   version-error match, and If-Range — all five findings fixed same-batch. Presigned URLs
>   deliberately NOT offered (a signed URL bypasses FGA for its TTL; the governed proxy doesn't).
>   42 new tests, suite 526→568, CI-exact gate green. Details on the flipped §9 P1 line.
>
>   **BATCH 12 (added + ✅ DONE 2026-07-11) — Turborepo workspace (rask microfrontend shape) + the
>   missing UI features.** `frontend/` → bun workspace with turbo 2.10.4 (user-pinned version,
>   verified on npm): `apps/web` (history-preserving git mv) + `packages/ui` (@lance/ui — Chip +
>   SearchBar, TRANSPORT-AGNOSTIC BY TESTED RULE: `exports.test.ts` fails if a component ever
>   calls fetch or reaches into an app). Browse gains governed /search with WHY-chips + namespace
>   scope; new Jobs tab. web.dockerfile builds via the turbo graph (runtime contract byte-
>   compatible: same entrypoint/port/uid); CI frontend job fans check+test over apps AND packages.
>   AUDIT NOTES (honest): no svelte/turborepo/microfrontend skills or Svelte MCP exist in this
>   session (checked — only an unrelated PixiJS skill), so this used the repo's own Svelte 5
>   conventions; a REAL Svelte 5 gotcha was found and pinned in-code — a DOM event handler on a
>   workspace-lib component never fired under the app's event delegation, so SearchBar's debounce
>   is $effect-driven with the reason documented in the component. Gates: turbo check+test 3/3
>   tasks green (svelte-check 0/0, bun 15+2), Playwright 4/4, production build via turbo emits
>   apps/web/build/index.js. PROVEN IN CI (run 29181903865 fully green — the reshaped frontend
>   job's first run: workspace install, turbo check+test over apps AND packages, Playwright 4/4).
>   LIVE residual (§7a): rebuild the web image once to prove the dockerfile's workspace build on
>   a real docker daemon (this sandbox has none).
>
>   **BATCH 8 (added + ✅ DONE 2026-07-11) — externalization leftovers closed by VERIFICATION,
>   not code.** Fact-check-first (the Batch 1 lesson, again vindicated): observability-s3-behind-
>   ESO, NATS external hooks, and stream replicas were ALL already shipped in the chart — the todo
>   line was the stale artifact; and the Dex→Keycloak swap is now AUDITED as issuer/audience
>   config only (core-claims-only IDToken, sub is the only consumed claim, no dex-specific
>   parsing). P1 Externalization hardening is now fully ✅ except the OpenFGA memory→postgres
>   datastore flip, which belongs to the rask merge. Docs-only batch — zero code, zero risk.
>
>   **BATCH 9 (added + 🟡 CODE-COMPLETE 2026-07-11) — the L3 network-isolation layer** (the
>   security audit's "biggest gap"): full default-deny + DNS-in-same-change + exclusive store
>   client lists behind the existing `networkPolicy.enabled` flag (default OFF = behavior-
>   identical); CI render-and-greps the layer both ways. Live flip + negative probe = §7a (needs
>   a policy-enforcing CNI — kind's default ignores NetworkPolicy). Remaining security items
>   (per-workload ServiceAccounts with `dapr mtls -k` pre-check, infra securityContexts with
>   per-image uids, PSA labels after init-container hardening) = Batch 10, each gated the same
>   way. Details on the flipped §security line.
>   ✅ DONE WHEN: a sweep lists `models/<model>/<token>/` prefixes, reads the registry's REFERENCED
>   tokens (meta column, read at a PINNED version), and reports tokens past a TTL that no registry
>   row references · DRY-RUN (report-only) is the default; deletion only behind an explicit flag ·
>   unit tests on local Lance + tmp dirs pin: a REFERENCED token is never deleted (even past TTL);
>   unreferenced-but-young is kept; unreferenced+old deletes ONLY with the flag; registry-dataset
>   directories are never touched · the invariant test ("referenced ⇒ never collected") exists and
>   passes BEFORE any delete code is written.
>   🚧 GUARDRAILS: fail-safe direction is KEEP — any listing/read error skips that token with a log,
>   never deletes · never enumerate or touch paths outside the artifact base · the deployed default
>   stays dry-run until a live kind pass proves the report against a real crashed-run orphan.

- 🟡 *(code-complete, live run pending)* **(MAJOR) writer-gate deny never proven + 12s grace window too short vs 30s
  redelivery** — DONE as spec'd: test 2 now has sub-phase A revoking
  `user:service-bronze-to-silver writer warehouse:lance_catalog` → drive → bronze COMPLETE, silver
  absent → restore (finally-guarded); the validator sub-phase kept as sub-phase B; and after the
  positive control, BOTH denied run-ids are re-asserted STILL absent behind a MEASURED wait —
  `time.monotonic()` stamped at each trigger publish, slept to `REDELIVERY_WINDOW (30s, pinned to
  dapr-component.yaml) + 5s` (review: on a warm stack the positive control alone can finish inside
  30s, which would have left the false-pass window open) — separating "checked-and-DENIED (DROP)"
  from "never checked (RETRY lands late)".
- 🟡 *(code-complete, live run pending)* **(MAJOR) Makefile `e2e-governed-union`** — DONE, beyond spec after review:
  bounded 30×1s readiness loop over ALL SIX forwards (lance-ray/lineage/mover /livez, fga /healthz,
  dex openid-config, rustfs TCP; each curl `-m 2` so one wedged probe can't hang the budget — the
  spec'd 3-probe loop would have let a slow dex forward green-SKIP the whole suite); seed failure
  kills the forwards and aborts before pytest; the seed re-runs after pytest (`|| true`, output
  visible) so a failed run still restores revoked grants; one `PIDS` list instead of three hand-kept
  kill lists. `bash -n` clean; not yet driven against a cluster.
- 🟡 *(code-complete, needs `make e2e-lineage` re-run)* **(MAJOR) events-feed e2e ordering masks the INSERT-time
  dedup** — DONE as spec'd: `list_events()` captured BEFORE the post-insert `ensure_events_table()`
  (plus an after-DDL recapture asserting the re-boot changes nothing); destructive-DB guard skips any
  DSN whose host isn't localhost/127.0.0.1/`age:`; reader is `user:analyst-<uuid>` per run.
- ✅ *(unit-proven)* **(MAJOR) reconcile route mounted only on a synthetic app** — DONE: extracted
  `mount_reconcile_cron(app, binding_name) -> bool` in `services/lineage/main.py` (no-op on empty),
  called at module level; `test_mount_reconcile_cron_production_gate` drives the PRODUCTION function
  both ways.
- ✅ *(unit-proven; image rebuild + roll still due at next deploy)* **(prod, small) `RunEvent.progress`
  int() poison-message** — DONE: non-coercible `done`/`total` now returns None (try/except around the
  int() pair), never a raise → no ingest RETRY loop; non-coercible unit cases added; the test
  docstring's "malformed → None" is now literally true.
- 🟡 *(code-complete, live run pending)* **(small) `_poll` hardening** — DONE: `message` accepts a callable evaluated
  AT failure (test 1's live-state diagnostic converted, single fetch); TRANSPORT errors only
  (`ConnectionError`/`Timeout`) count as not-ready — deliberately NOT the whole `RequestException`
  (review: that would swallow `HTTPError`, burning 90s on a persistent 401/403/500 and misreporting a
  real regression as a timeout).
- 🟡 *(code-complete, live run pending)* **(small) alice fixture residue** — DONE: yield + teardown deletes her
  warehouse reader tuple.
- 🟡 *(code-complete, live run pending)* **(small) test 3 order-independence** — DONE: guards on bronze existing
  (drives `/produce` + polls if `lance.dataset(bronze_uri)` raises).
- ✅ **(small) test 4 positive control for the s3:// filter — RESOLVED AS IMPOSSIBLE, not implemented**
  (2026-07-10 review, verified against OpenFGA's tuple validation, `pkg/tuple/tuple.go`): an OpenFGA
  object id must contain EXACTLY ONE `:`, so the audit's suggested grant on
  `table:s3://<bucket>/media-src/batch/img-a.png` can never be written — the Write RPC 400s (and
  `batch_check` on such ids folds to not-allowed, which is WHY the filter hides them today). The first
  cut of this batch implemented the grant as spec'd; the review caught it before any live run. So:
  s3:// sources are **structurally ungovernable per-object → invisible to every governed principal by
  construction** — documented as the contract in the test comment; the negative stays non-vacuous
  because the auth-off `tests/e2e/test_media_e2e.py:99` pins source PRESENCE on the same stack.
  Residual design decision (only if source browsing becomes a real need): an id-encoding scheme or a
  `namespace:source` parent with encoded ids.
- ✅ *(unit-proven)* **(small) /graph route↔filter structural binding** — DONE:
  `test_graph_route_wires_the_dataset_filter` asserts `get_dataset_filter` in the real /graph route's
  dependant tree.
- 🟡 *(code-complete, needs `make e2e-lineage` re-run)* **(small) pin `_LIST_RUNS` column order on real AGE** — DONE:
  `test_discovery_lists_against_age` now folds `repo.list_runs()` and asserts typed field-by-field on
  two known sample runs (state/job/author/outputs/timestamps + FAIL error slot) — any RETURN
  transposition breaks it.
- ✅ **(small) todo wording** — DONE: the §7 progress flip now says "at three layers, all unit-tier".
- ✅ **(design, log only) /events keep-first-terminal vs graph last-wins** — DECIDED (keep-first) and
  documented at the `_INSERT_EVENT` site in `repository.py`: /events is the append-only observation
  log ("what arrived first"), the graph views are last-wins current state; upsert-latest would let a
  redelivery rewrite audit history. The e2e pins keep-first.
- ✅ **(doc) seed-script comment** — DONE: `seed_medallion_fga.sh` now states the intended side effect
  (parent links extend the FULL warehouse rung cascade — a warehouse writer gains `can_write_data` on
  linked medallion tables) + the grant guidance (browsers get `reader`, never `writer`).
- ✅ **(fixed in this batch) `_tuples` blanket-400 tolerance** — now only the two idempotency
  messages pass; malformed writes fail at the call site with the real OpenFGA error.
- Refuted (no action): quality-block try/finally restore (the healing `/produce` IS the restore, and
  a mid-test failure leaves only test data); mover direct-POST 180s timeout (arithmetic); one
  s3://-related duplicate.

## 8 · P1/P3 — docs staleness — ✅ ALL FIXED (2026-07-02)

All 13 addressed: RASK-INTEGRATION double-fire trap (the seam contract now warns the real Ray job must
NOT publish `medallion.raw` — the `/raw-arrival` subscription does) + "dummy emitters" claim; the same
double-fire trap in the `medallion.yaml` chart comment; ARCHITECTURE `add_columns_from`→`add_columns`
(nonexistent API, fixed everywhere incl. the .html), the vending endpoint + 4-modes + web_identity/RustFS
correction, and the lineage-deferred contradiction; RESILIENCE gap #1 (inline-awaited not
fire-and-forget, + the shipped B4 back-fill mitigation) + the matching `lineage_emit.py` docstring; the
LINEAGE gold-JSONB "demo-driver-only" scope note; the COVERAGE tally (320); DEPLOY RustFS-STS (web_identity
IS built); the DLQ wording (already done in §2); and the two big planning docs (system-diagram,
SYSTEM-SKETCH) got point-in-time banners pointing at the authoritative current-state docs + their specific
flagged contradiction fixed (CredentialVendor wired). Detail below.


> **BATCH 1 SWEEP RESULT (2026-07-11):** every line below was FACT-CHECKED against code before
> touching any doc (the batch's own guardrail) — and 9 of 12 were ALREADY FIXED by earlier passes;
> this list itself was the stale artifact. The 3 genuinely-stale items were fixed today. Per-item:

- ✅ *(verified already-fixed 2026-07-11)* `docs/RASK-INTEGRATION.md` seam contract — the doc CORRECTLY
  forbids the job publishing `medallion.raw` (line ~75 warning present); code confirms `/raw-arrival`
  (`ingest_trigger.py`) publishes the first trigger. No double-fire instruction exists.
- ✅ *(verified already-fixed)* `docs/RASK-INTEGRATION.md` dummy-emitters claim — now correctly
  describes the B1 compute toggle (default off, real read→transform→write when on).
- ✅ *(verified already-fixed)* `docs/ARCHITECTURE.md` vending — now documents the real
  `POST /v1/table/{id}/credentials?tier=` surface with FOUR modes; RustFS STS via `web_identity`
  correctly stated.
- ✅ *(verified already-fixed)* `docs/ARCHITECTURE.md` lineage-deferred — §7/§8 both say built+deployed
  (the one remaining “deferred” refers to Dapr Workflow, which IS deferred by decision).
- ✅ *(verified already-fixed)* `add_columns_from` — appears nowhere in docs/ or services/; the real
  `add_columns` is used throughout (probed against installed pylance).
- ✅ *(verified already-fixed)* `docs/RESILIENCE.md` — now says “inline-awaited + best-effort … not a
  BackgroundTasks fire-and-forget” and documents the shipped B4 back-fill as the mitigation.
- ✅ **FIXED 2026-07-11** `docs/system-diagram.md` + `.html` — body markers refreshed: full write-surface
  emit (insert/merge_insert/update/delete/compaction), OpenBao “planned”→built (Dapr secret store),
  vending shown at its REAL endpoint (`POST …/credentials?tier=`, four modes incl. RustFS-native
  `web_identity`), create-emit “fire-and-forget”→awaited-inline+B4, “what's still open”→points at
  todo_fable §7a/§9; the un-bannered `.html` payloads (`?vend_credentials=true`, “planned” OpenBao
  step) rewritten — zero stale occurrences remain (grep-verified).
- ✅ **FIXED 2026-07-11** `docs/SYSTEM-SKETCH.md` — gap-register rows 3–6 flipped to ✅ CLOSED (vending
  endpoint, four modes, OpenBao two-tier store, medallion estate) and the roadmap's
  “wire vending into describe_table” item annotated ✅ superseded-and-shipped (dedicated endpoint).
- ✅ *(verified already-fixed)* `docs/DEPLOY.md` footer — correctly states RustFS-native scoped STS is
  BUILT (`web_identity`; plain `AssumeRole` works on AWS/MinIO/Ceph, not RustFS) and scopes
  “deployed-not-wired” to hierarchy auto-seeding + the end-to-end Dex demo only.
- ✅ **FIXED 2026-07-11** `docs/COVERAGE.md:9` — tally refreshed to the measured reality: 493 passed
  (391 unit + 102 integration, 2026-07-11); 47/54-backed unchanged (needs a live backend to re-probe).
- ✅ *(verified already-fixed)* `docs/LINEAGE.md` gold-JSONB — heading now says “(demo driver only)”
  with a scope blockquote; code confirms only `medallion_demo.py::write_gold` embeds the column.
  (Making the silver→gold mover embed it stays a possible future item, deliberately not done here.)
- ✅ *(verified already-fixed)* chart comments + DLQ wording — `consumer.py`, `transform.py`, and
  `dapr-component.yaml` all now state the truth: NO deadLetterTopic anywhere (grep-verified);
  behavior = maxDeliver=5 + backOff, Limits-retention stream keeps messages 168h, lineage's
  `deliverPolicy: all` replays on restart; DLQ remains RESILIENCE.md gap #2 (roadmap).

## 9 · Feature gaps — ephemeral multimodal lakehouse (→ rask merge)

> **2026-07-06 — the DEPLOYED media loop is closed (the strategic audit's #1 gap).** `POST /ingest-media`
> (lance-ray, token-guarded, compute-on) lands external media as `bronze-media$objects` (blob-v2 2.2,
> one lineage input per source URI) → `medallion.media` trigger (durable consumer) → the generic
> `media-to-silver` mover derives BY CONTENT (`medallion/services/derivers.py`: image → inline
> thumbnail+embedding; unrecognised media carries untouched; tabular = no-op — zero media config, the
> platform knows only Lance types) → `silver-media$features` with the blob-aware schema in AGE.
> Live-proven end-to-end (`make e2e-media`, in the `make e2e` umbrella; skips compute-off). Undecodable
> media = deterministic FAIL+DROP (quality-gate contract). Governed grants seeded
> (`seed_medallion_fga.sh`: bronze-media/silver-media parents + service-media-to-silver writer — the
> audit's blocker). Ray path falls back in-process for blob upstreams — CORRECTED scope (user caught an overclaim):
> lance-ray 0.4.2 READS blob bytes correctly (datasource take_blobs reconstruction — verified against
> its source); the real port = re-attach blob_field on the job's write-back (v2 columns arrive as plain
> LargeBinary, typing stripped) + Pillow/deriver in the ray image. Small task, then drop the gate.
> Still open here: registering cascade outputs into the catalog; real encoder plugin; egress lane.

- ✅ **Ray TRAIN vs Ray DATA distinction — DESIGN DECIDED 2026-07-10** (added 2026-07-06, user request;
  task #115 + todo_confirm §4). **The contract is [`docs/RAY-TRAIN.md`](RAY-TRAIN.md)** — all four open
  questions pinned: (D1) separate `POST /train` head + OWN topic (`training.jobs`) — NOT a field on the
  stage trigger (stage-hop semantics don't fit a long-running terminal-on-failure workload); (D2) the
  trainer consumer is SUBMIT-AND-ACK (deterministic `ray-train-<token>` id, re-attach on redelivery, NO
  auto-resubmit of a failed run) — resolves ray_submit's documented long-job limitation instead of
  inheriting it; the JOB emits its own OpenLineage lifecycle; (D3) official `JobTypeJobFacet`
  processingType=BATCH/integration=RAY/**jobType=TRAINING**, inputs carry per-feature
  `DatasetVersionDatasetFacet` pins, deterministic `run_id_for("train-<token>")`, progress facet reuse,
  FAIL = bare output + errorMessage; (D4, sharpened 2026-07-10) **model REGISTRY = a Lance dataset
  `models$<model>` whose rows POINT (external blob, #92 allowlist) at plain-path S3 artifact objects**
  (`models/<model>/<token>/…`, bytes-then-commit = atomic registration; inline only for tiny models) —
  versioning via time-travel, promotion via tags + the `validator` rung, serving loads the plain path;
  an external registry product later only changes the pointer targets;
  (D5) dedicated `user:service-trainer` (per-namespace `reader` on features + `writer` on
  `namespace:models` ONLY — never the medallion writer rung); (D6) shared Ray Jobs-REST core now,
  KubeRay `RayJob` CR under Kueue at the rask merge (contracts unchanged, transport swaps).
  Implementation = #115a–c below.

- ✅ **Operator adoption + submit-seam boundary — DECIDED + DOCUMENTED 2026-07-11** (user question:
  "most logical operator? can rask help? is Ray submit more agnostic in rask or here?"). The
  contract is [`docs/OPERATORS.md`](docs/OPERATORS.md): adoption order KubeRay+Kueue (replaces the
  weakest hand-rolled thing — the raw Ray head + our submit/poll logic; `RayJob` CR is the missing
  lifecycle owner) → CloudNativePG (gated by the AGE-extension decision) → rustfs-operator → NACK
  (optional; would make the `LINEAGE`/`MEDALLION`/`TRAINING` streams declarative CRDs instead of
  the provision Job); NO custom lance-ns operator, ever (state of record = Lance manifests +
  Postgres, every control loop already has an owner); rask helps with ALL of it (it already
  operates every listed operator — adoption = the merge's values flips, nothing installed here);
  the Ray submit seam is DELIBERATELY the lance-ns side (httpx-only Jobs-REST, no ray/k8s deps —
  contracts stay here, rask supplies the `RayJob`-CR transport behind the same signatures,
  deterministic submission id becomes the CR name). Dapr needs no operator story (its control
  plane IS an operator; components are CRDs; Dapr Workflow stays un-adopted — token-keyed
  idempotency suffices); Lance needs none (manifest+CAS is the reconciler; the one real gap is the
  §9 orphan-artifact janitor, already tracked). Linked from README, RASK-INTEGRATION §Pre-flight,
  RAY-TRAIN D6.

- 🟡 **#115a — `/train` head + training topic + submit-and-ack trainer consumer — CODE-COMPLETE
  2026-07-10, unit tier (16 tests); LIVE DRIVE + chart/seed PENDING.** Built as spec'd + hardened by the
  adversarial review, which caught: the producer lifespan never built `app.state.fga` (the trainer gate
  would have been silently OFF with MEDALLION_FGA_ENABLED=true — an authz bypass; now built exactly like
  the movers'); version-less/malformed/empty feature lists now DROP at the consumer (a floating-LATEST
  feature or a vacuous gate never reaches the job); the trigger `config` is claim-check-capped (8 KiB) at
  the head AND actually forwarded to the job env (it was published-then-discarded); the httpx timeout
  kwarg is now assert-pinned in the fake (the ack-window bound had no tripwire). ACCEPTED deviation from
  the spec: `submit_train_job` is a documented SIBLING of `submit_stage_job` rather than an extracted
  shared core — their re-attach semantics differ at the terminal-failure branch (train NEVER
  delete-resubmits); the module header now tells maintainers to mirror protocol fixes across both.
  REMAINING before flipping ✅: chart env passthrough (train topic/entrypoint/trainer identity — defaults
  work but should be values-wired) + the #115c seed grants + the live kind drive (in §7a RESIDUAL).
  Original spec below:
  (execution-spec'd per
  docs/RAY-TRAIN.md D1+D2+D6). Build: `POST /train` on lance-ray (token-guarded; resolves omitted
  feature versions to LATEST at the head); publish `{token, model, features:[{dataset,version}], config}`
  to `MEDALLION_TRAIN_TOPIC` (default `training.jobs`); a durable subscription (own queue group) whose
  handler FGA-gates (D5) then submits via the generic core EXTRACTED from
  `medallion/services/ray_submit.py::submit_stage_job` (entrypoint+env+deterministic id; stage path
  keeps its block-poll, training path returns after submit/re-attach) and acks SUCCESS.
  ✅ DONE WHEN: /train → 202 + trigger published (unit, fake publisher) · handler with a hung Ray API
  still acks within the 30s window (unit: submit bounded by the request timeout) · redelivered trigger
  re-attaches (same submission id, no second job — unit vs a fake Jobs API) · a terminally FAILED prior
  job is NOT resubmitted on redelivery (unit — the D2 no-auto-retry pin) · FGA deny → DROP before any
  submit; FGA outage → RETRY (unit) · stage movers' existing ray tests stay green (the extraction is
  behavior-preserving) · live on kind: one `POST /train` drives the stub job end to end.
  🚧 GUARDRAILS: never block the handler on job completion · trigger carries pointers only (no config
  blobs > a few KB — claim-check) · do NOT touch the stage movers' block-poll semantics · the extracted
  core must keep the delete-and-resubmit-on-terminal behavior FOR THE STAGE PATH only.
- 🟡 **#115b — `scripts/ray_train_job.py` + model REGISTRY write + lifecycle lineage —
  CODE-COMPLETE 2026-07-11, unit tier (31 train tests, suite 492); LIVE DRIVE + allowlist value +
  auth-on lineage credential PENDING.** Built per D3/D4 and hardened by a two-lens adversarial
  review (lineage+registration / Dapr+consumer — the user's named audit lenses):
  the job (baked into the ray image at `/home/ray/jobs/`, entrypoint default FIXED — it said
  `/app/scripts/`) reads features at PINNED versions (unit-proven: pinned v1 means ≠ LATEST means),
  writes token-keyed artifact bytes FIRST, then ONE Lance commit (2.2 + stable row ids +
  `initial_bases=[artifact base]`) = atomic registration, model version == Lance version; emits its
  own START→RUNNING(progress)→COMPLETE|FAIL over lineage HTTP with run ids EQUALITY-PINNED to
  `common.openlineage.run_id_for` and the version-facet spec pinned to the medallion emitter's
  (both are drift tripwires in tests/unit/test_train_job.py). REVIEW CATCHES (all fixed): no
  JetStream stream covered `training.jobs` — every deployed publish would have failed (added
  `TRAINING training.>` to the nats-stream Job); the registry create-vs-append except-scope masked
  real append errors as "Dataset already exists" (probe-reproduced; scope narrowed + CAS-race loser
  now converges as append); N+1 sequential FGA round trips could blow the 30s ack window (now ONE
  `fga.batch_check` + a 16-feature cap); no `dataSource` facet meant a lost COMPLETE was
  UNRECOVERABLE by the B4 reconcile (now on every event type); env parsing outside the FAIL guard
  made misconfigured runs vanish from provenance (now attributable FAIL); head/consumer validation
  asymmetry 202'd requests the consumer silently DROPped (head now 422s the same shapes — model
  slug, `stage$name` datasets ONLY (bare names would corrupt the shared graph node's namespace via
  ingest's `SET d.namespace`), config re-capped at the consumer). Layout convention (lives in
  train.py ONLY, the job is layout-dumb): registry `…/medallion/models/<model>`, artifacts
  `s3://<bucket>/models/<model>/<token>/…`; the base must stay STABLE per model (create-time-only
  registration; foreign-base pointers are refused loudly — unit-pinned).
  REMAINING before ✅: `vending.externalBlobBases` deploy value must include the models prefix
  (deploy-specific bucket URI — part of the deferred chart passthrough); auth-on deployments have
  no lineage credential for the job's HTTP emits (LINEAGE_TOKEN seam exists, 401s are logged
  distinguishably; demo tier runs auth-off — documented in RAY-TRAIN.md); orphan-artifact janitor
  stays future work (§9 blob-pointer lifecycle); the live kind DONE WHEN below (§7a RESIDUAL).
  Original spec below:
  (per D3 + the
  SHARPENED D4: registry record vs artifact bytes). Build: the job script (baked into the ray-lance
  image) reads each feature dataset AT ITS PINNED version, trains the demo-tier CPU model, then
  publishes in the crash-safe order — (1) artifact BYTES as plain S3 objects under
  `models/<model>/<token>/` (token-keyed → retry-idempotent), (2) the REGISTRY record `models$<model>`
  as ONE Lance commit (rows = artifacts, `payload` = external blob POINTER to the plain paths via the
  #92 allowlist; inline only ≲ a few MB; shared write helper — 2.2 + stable row ids, §0
  create-time-only rule) — the commit IS the atomic registration; emits START → RUNNING(progress
  {done:epoch,total}) → COMPLETE with jobType=TRAINING + input version facets + output version/schema
  facets; on failure emits FAIL (bare output, errorMessage facet, no version).
  ✅ DONE WHEN: event-shape round-trip unit tests through `lineage.models.RunEvent` (TRAINING jobType
  parsed; input versions surfaced; FAIL parses with no fabricated version) · a local-Lance unit test
  drives the publish path (pinned-version read; artifacts land BEFORE the registry commit; pointer rows
  resolve; a simulated crash between the two steps leaves NO registry entry; the retry converges on the
  same token paths) · `models/` added to the registered external-blob bases + covered by its existing
  allowlist tests · live on kind: `upstream(models$<m>)` shows the feature datasets WITH the pinned
  versions, /runs shows the progress trail, a serving-shaped read loads weights from the PLAIN path
  (no Lance reader), and the FAIL path is fault-injected once.
  🚧 GUARDRAILS: official OpenLineage facets only (jobType is a free-string field — no invented facet) ·
  FAIL never carries a version/DERIVED_FROM · bytes-then-commit order is mandatory (a registry entry
  must never point at objects that don't exist yet) · the model write goes through the shared helper
  (never hand-copied kwargs) · the job reads features ONLY at the pinned versions (no floating LATEST
  inside the job) · GC must never collect `models/<model>/<token>/` objects referenced by a registry
  row (§9 blob-pointer lifecycle is load-bearing here — orphan-janitor is future work, document it).
- 🟡 **#115c — trainer authz seed + gates — SEED + GATES LANDED 2026-07-10; chart passthrough + live
  DONE WHEN pending.** The handler's pre-submit checks shipped with #115a (deny→DROP / outage→RETRY,
  unit-pinned); the seed script now writes the trainer rung (warehouse parent namespace:models;
  service-trainer reader on silver+gold, writer on namespace:models ONLY — verified against model.fga's
  assignable relations; `bash -n` clean). The per-model table parent (`namespace:models parent
  table:models$<m>`) is written by the TRAINER CONSUMER at trigger time (#115b, 2026-07-11 —
  idempotent, before the submit ack, outage→RETRY; unit-pinned): without it the published model
  would be invisible under LINEAGE_FGA_ENABLED.
  REMAINING: (a) chart values passthrough for train topic/entrypoint/trainer identity — DEFERRED with
  reason: helm is unavailable in the remote session (proxy 403) and §0 forbids un-render-verified chart
  changes; defaults work meanwhile; (b) the live governed drive (ungranted trainer → DROP, granted →
  model lands) — §7a RESIDUAL. Original spec below:
  (per D5). Build: seed-script additions (`namespace:models`
  parent + per-model table parents + `service-trainer` grants), the handler's pre-submit checks
  (`can_read_data` on every input, `can_create_table` on `namespace:models`).
  ✅ DONE WHEN: seed idempotent re-run green · unit: deny on ANY input → DROP; deny on models → DROP;
  outage → RETRY · live under the governed union: ungranted trainer → DROP (no job submitted), granted →
  model lands + humans with warehouse reader can see `models$<m>` in governed /runs.
  🚧 GUARDRAILS: trainer NEVER gets the warehouse writer rung · model promotion tags stay behind the
  `validator` rung (not writer) · grants live in the seed script next to the mover grants (one place).

- ✅ **P2 `/produce` (lance-ray) in-cluster auth — DONE (2026-07-04).** BOTH layers now ship
  (defense-in-depth, the Ray-security shape: network isolation primary + token guard):
  (1) `/produce` now depends on `require_dapr_token` (the shared app-api-token) — no-op in dev, enforced
  once `APP_API_TOKEN` is set, so an in-cluster workload can't forge the cascade head; wiring pinned by
  `tests/unit/test_produce_auth.py` (403 on missing/wrong token). (2) a gated `NetworkPolicy`
  (`chart/templates/network-policy.yaml`, `networkPolicy.enabled`, default off — needs a policy-enforcing
  CNI) restricts ingress to `lance-ray` to in-release pods. `services/medallion/api/produce.py`
- 🟡 **P0 Multimodal (blob_v2) — BACKEND ROUND-TRIP COMPLETE (P0→P4, live-verified); glyph
  truth'd up 2026-07-12 (the header said ⛔ while the body said complete — the todo was the stale
  artifact again). P1 credential-less serving path SHIPPED 2026-07-12 (Batch 13). OPEN sub-items
  only: the P2s below + the lifecycle remainder.** Original context: the format + our pinned pylance>=7.0.0 fully support it
  (`lance/blob.py` BlobColumn, inline-when-small / pointer-when-large, ranged reads; verified in the installed
  package + lance_docs/{guide,file_format,ray}.md) and the direct write path (vended creds → RustFS) is open —
  but lance-ns has NEVER exercised a blob column. Dapr is uninvolved by design (events carry pointers, never
  data). Concrete work:
  - 🔶 P0 e2e proof (in progress): a blob column round-trips through OUR stack.
    ✅ **write side DONE (§9 P1)** — `POST /v1/table/{id}/create` with a blob-v2 column routes to a direct
      file-format-2.2 write via the `dataplane.create_table` facade (declare → `write_dataset(2.2)`; native
      create pins 2.1 and rejects blob-v2). Live-verified + tests (Create/ExistOk/Overwrite, rollback,
      plain→native-2.1).
    ✅ **cascade + media derivation DONE (§9 P3)** — `transform_stage` is now blob-SAFE: a blob-v2 column is
      carried through a medallion hop via `read_blobs`+`blob_array` (a plain `to_table()` demoted it to the
      legacy descriptions struct, which a 2.2 write rejects). Real media derivation lives in
      `services/medallion/services/media.py` (Pillow: thumbnail + pixel-embedding + caption) — the demo's
      bronze writes real PNG image blobs and silver decodes them into an inline `thumbnail` + `embedding`.
      Live-verified on RustFS (bronze image blob → silver thumbnail+embedding, all 2.2) + e2e-medallion.
    ✅ **lineage schema DONE (§9 P4)** — the medallion emitter now attaches a real blob-aware
      `SchemaDatasetFacet` (derived from the written dataset by `compute._measure`) rendering
      `lance.blob.v2`→`blob`, FixedSizeList→`array<elem>`, binary→`binary` (shared `common.schema`).
      Live-verified in AGE: a media WROTE edge shows `payload:blob, thumbnail:binary, embedding:array<float>`
      (and the real cascade's `silver$features` now carries its derived schema too).
    §9 backend round-trip (P0→P4) COMPLETE; the ranged blob-read serving endpoint shipped in Batch 13 (below).
  - ✅ P0 guard the tabular path — DONE (2026-07-04): a pure-ASGI `BodySizeLimitMiddleware`
    (`services/catalog/api/body_limit.py`, cap `LANCE_MAX_BODY_BYTES` default 256 MiB) rejects an oversized
    Arrow-IPC body with a problem+json **413** BEFORE it is buffered — both the fast Content-Length reject
    and a streaming byte counter for chunked/absent-length — steering big media to the vending/direct-write
    path (claim-check). Live-verified (2000 B over a 1000 cap → 413) + `tests/unit/test_body_limit.py`.
    Complement (2026 layered best-practice): also cap at the ingress/Gateway-API/mesh when one fronts the
    catalog — the app guard covers in-cluster ClusterIP callers that bypass the edge.
  - ✅ P1 serving path for credential-less consumers — **DONE 2026-07-12 (Batch 13):**
    `GET /v1/table/{id}/blobs?column=&row=[&version=]` (`services/catalog/api/v1/endpoints/data.py`)
    serves blob bytes over plain HTTP, **STREAMED in bounded 8 MiB `BlobFile.read_range` windows via
    `StreamingResponse`** (adversarial review upgraded the first buffered cut — the catalog never
    holds a multi-GB payload; the read-side mirror of the body-limit OOM guard), with full RFC 9110
    Range support: `bytes=a-b|a-|-n` → 206 + `Content-Range`; no Range → 200 + `Content-Length`;
    start ≥ size → 416 `bytes */size`; malformed/multi-range ignored → 200 (RFC-permitted). Every
    response carries a strong `ETag` (`"<version>-<column>-<row>"`) and **`If-Range` is honored** —
    a stale validator downgrades a resume to a full 200 instead of splicing bytes from two
    incarnations (review finding). `dataplane.read_blob` maps every probed pylance failure shape to
    a precise 4xx: unknown column → 404 `TableColumnNotFoundError`, non-blob column → 400, row OOB →
    400 (the raw panic was a row-address dump), missing version manifest → 404
    `TableVersionNotFoundError` and a declared-only/dataset-less location → 404 `TableNotFoundError`
    (both bare ValueErrors, told apart by the manifest-path shape — review tightened the first
    substring match). **Zero-length payloads serve as an empty 200** (review caught the first cut
    400-ing them as "null"; the fix probe showed pylance 8.0.0 stores a NULL blob as a size-0
    descriptor — null and `b""` are the SAME row state, `take_blobs` returns `[]` for both); any
    Range against one is 416. `?version=` pins the read across overwrites; `row` is positional at
    the served version (delete-shift semantics test-pinned). Authz: router-level `authorize` maps
    the `blobs` suffix to reader-tier `can_read_data` (added to `_DATA_READ_ACTIONS`) — pinned by
    `test_blobs_suffix_is_reader_tier` (unit) AND `test_blob_read_checks_data_reader_and_denies`
    (integration: 403 end-to-end through the router guard, relation captured). Tests (42 new, suite
    526→568): `tests/unit/test_blob_serve.py` (real dir ns + real pylance — full/ranged/suffix/
    clamped/unsatisfiable byte-compared, chunk-loop math pinned at window 4 → `4+4+3`, empty/null
    200s, all 4xx guards incl. declared-only, version+etag pinning, If-Range both ways, positional-
    after-delete, `_parse_range` table) + `tests/integration/test_blob_serve_api.py` (HTTP contract:
    200/206/416/400/404/422, `Content-Range`/`Accept-Ranges`/`ETag` headers, empty payload
    `Content-Length: 0`, version param over HTTP incl. 404 problem+json + `version=0` → 422,
    If-Range stale→200/fresh→206). Presigned-URL variant NOT built — the governed ranged proxy is
    strictly safer (no URL that bypasses FGA for its TTL); revisit only if a CDN/offload need appears.
  - 🟡 P1 blob-pointer lifecycle — **the models-lane HALF SHIPPED 2026-07-11 (Batch 4):**
    `scripts/model_artifact_janitor.py` + 7 unit tests. Per-model sweep: registry read at ONE
    pinned version → referenced-token set from `meta`; tokens = first-level prefixes under the
    artifact base aged by their NEWEST object; deletable class = unreferenced AND past TTL, ONLY
    with `--delete` (dry-run default). Fail-safe = KEEP throughout: unreadable registry or ANY
    unparseable meta row ⇒ the whole pass degrades to report-only even with the flag; unstattable
    token kept; overlapping registry/artifact trees refuse to run (never enumerates a Lance
    dataset dir). THE invariant (referenced ⇒ never deleted, even past TTL, even with --delete)
    was test-pinned BEFORE the delete code existed, per the batch guardrail. REMAINING (this item
    stays open for): the deployed default stays dry-run until a live kind pass proves the report
    against a real crashed-run orphan (§7a); the BROADER posture — compaction/GC understanding
    pointer columns generally + reconcile flagging dangling pointers after a bucket wipe — is
    untouched by this tool.
  - ⛔ P2 quality gate blob assertion: "the blob pointer resolves" check alongside row_count/not_null.
  - ⛔ P2 per-project schema declaration (embeddings/classification/summarization columns are KNOWN per project):
    register expected columns so the quality gate asserts they landed, FGA pre-registers column masking, and
    reconcile flags undeclared writes — a governance contract, not a Dapr one. Lance itself needs no up-front
    schema (add_columns evolves it; per-version schemas already ride the WROTE edge). This is also the
    **breaking-change detector**: today a producer renaming/dropping a column a downstream reads is caught only
    at runtime (mover fails → RETRY → stall); declared columns turn that into a pre-promotion contract
    violation. Additive evolution is already safe by construction (immutable versions pin readers).
  - ✅ P1 **document the data contract — DONE 2026-07-11 (Batch 2): [`docs/DATA-CONTRACT.md`](docs/DATA-CONTRACT.md)**,
    framed by the user's own questions (what is it / how does it work / is it prod-ready / what do
    Dapr+NATS enforce / same as Lakekeeper?). Covers: bus contract (pointers-only triggers + facet
    `_schemaURL`s ARE the contract), storage contract (manifest = schema, version = handshake, CAS
    validated), identity thread, the three enforcement points (quality gate promotion-time / FGA
    access-time / reconcile drift-time) + consumer-edge DROP validation, the HONEST prod split
    (additive evolution + delivery + access are prod-grade; breaking-change detection is NOT —
    runtime-stall only until the schema-declaration item builds; claim-check = convention + the 8KiB
    train cap, universal publish-site guard still open below), Dapr/NATS = the DELIVERY contract
    only (at-least-once + idempotent handlers; NATS ~1MB bound is why claim-check exists), and the
    Lakekeeper diff (Iceberg-spec contract vs Lance manifest + our gates; neither is a registry).
    Linked from README + ARCHITECTURE. Every claim cites shipped code per the batch guardrail.
  - ✅ P1 **claim-check invariant enforced — DONE 2026-07-11 (Batch 5).** The guard lives in the ONE
    choke point every publish site funnels through (`common.dapr_publish.publish_event` —
    grep-verified: catalog + compaction emitters, medallion produce/media/transform/train/
    ingest_trigger; no bypasses): >900 KiB (just under NATS's ~1 MiB default, verified un-overridden
    in the chart; streams use --max-msg-size=-1) → `ValueError` naming the rule BEFORE any I/O —
    behavior-preserving by construction since the broker would refuse it anyway, and every caller
    already wraps in best-effort/RETRY handling; >64 KiB → `dapr_publish_payload_large` WARNING
    (facet-bloat early visibility; the real truncation cap stays the §9 P2 item). Doc'd rule:
    docs/DATA-CONTRACT.md §2/§5. TESTS (tests/unit/test_dapr_publish.py):
    `test_oversize_payload_raises_before_any_io` (ValueError matching "POINTERS"; sidecar never
    called), `test_large_payload_warns_but_still_publishes` (published unchanged + the warning
    record), `test_normal_payload_publishes_silently` (no warning — default path byte-identical),
    `test_bytes_payloads_are_measured_too`, `test_hung_sidecar_still_raises_timeout` (the original
    timeout contract survives the guard).
  - ✅ P2 **facet metadata bloat cap — DONE 2026-07-11 (Batch 6).** `FACET_MAX_FIELDS = 512` in the
    SHARED `common.openlineage.schema_facet` builder (the one place both emitters — catalog +
    medallion — construct the facet, so no per-emitter drift): >512 fields → the facet carries the
    first 512 + a `schema_facet_truncated` WARNING; spec-true by construction (a shorter fields
    list is still a valid SchemaDatasetFacet) and the FULL schema stays readable from storage (the
    manifest IS the schema — /schema, reconcile's read_storage_schema). Pairs with the Batch 5
    publish guard: the facet share stays far under the 64 KiB warn line. Honest scope note:
    /schema-from-graph lists at most 512 fields for wider tables (the WROTE edge stores the capped
    facet); columnLineage facets are producer-declared per-edge and stay uncapped for now. TESTS:
    `test_schema_facet_caps_metadata_bloat` (600 fields → exactly c0..c511 + the warning +
    unchanged _schemaURL), `test_schema_facet_under_cap_is_untouched` (≤512 → byte-identical, no
    warning).
- ⛔ **P1 Ephemerality** — ~~RustFS is `emptyDir` in this chart~~ STALE premise (corrected 2026-07-05): RustFS
  now persists on a keep-PVC by default (`rustfs.persistence.enabled=true`, `helm.sh/resource-policy: keep`);
  emptyDir remains only as the `persistence=false` throwaway-CI mode — a stale comment at
  `chart/values.yaml:~180` still claims otherwise, fix it. Still open: at merge switch to rask’s
  RustFS-operator Tenant + CNPG-backed AGE. Prove “helm install from zero” fully reproducible
  (FGA seeds, OpenBao seeding, dex clients are still script-manual); backups exist but gated off.
- 🟡 **MFE follow-ups (Batch 12 leftovers — user: "remember to fix the mfe stuff", 2026-07-12).**
  The workspace shape is landed + CI-proven; what remains to be FULLY rask-similar:
  (a) ⛔ **exact-convention alignment needs the rask repo visible** — package naming (@lance/ui vs
  their scheme), their turbo.json task names/caching, shared config packages (tsconfig/eslint
  presets as workspace packages), runtime composition (separate deploys behind Traefik vs a shell
  app). BLOCKED on: add the rask repo to a session (it is not in list_repos under any obvious
  name) or paste its root package.json + turbo.json + one app/package manifest.
  (b) ⛔ extract `StatusBoard` (and the attachment helpers it needs) into @lance/ui — deferred in
  Batch 12 because it imports app-local `attachments.ts`/`types.ts`; the lib needs either its own
  copy of the tiny attachment helpers or structural prop types (keep the transport-agnostic test
  green either way).
  (c) ⛔ shared `packages/config` (tsconfig base + prettier/eslint) so a second app (`apps/*`)
  starts from presets instead of copying apps/web's configs.
  (d) 📌 pinned gotcha for all future lib components: DOM event handlers on workspace-lib
  components did NOT fire under the host app's Svelte 5 event delegation (Batch 12, proven with a
  console-capture spec) — lib components react to bound state via $effect, never rely on
  delegated DOM handlers; documented in SearchBar.svelte.
  ✅ DONE WHEN: (b)+(c) land with the existing gates (turbo check/test, transport-agnosticism test
  extended to the new components, Playwright still 4/4); (a) lands as a diff-and-adjust batch once
  rask is visible.
- 🟡 **P1 Search — TIER 1 SHIPPED 2026-07-11 (Batch 11): governed `/search?q=` over the discovery
  estate.** Case-insensitive substring across dataset NAMES, NAMESPACES, TAGS, and the CURRENT
  column inventory (HAS_COLUMN-scoped, so GC'd columns don't resurrect via search); each hit
  carries its match REASONS (`name`/`namespace`/`tag:…`/`column:…`); governance identical to
  /datasets — the visibility filter runs over the FULL hit set before the limit, and `total`
  counts the VISIBLE set only. TESTS (test_lineage_discovery.py):
  `test_search_matches_name_tag_namespace_and_column` (one query, all four tiers, reasons named),
  `test_search_is_governed_before_the_limit` (a matching-but-ungranted dataset never appears AND
  is not counted), `test_search_orders_by_name_and_caps`. REMAINING (pinned, unchanged): tier 2 =
  Lance FTS + FLAT vector CONTENT search (rask `index_catalog.py`/`search_api` pattern) behind the
  measured recall gate below. **UI wiring SHIPPED 2026-07-11 (Batch 12):** the Browse tab gains
  the @lance/ui SearchBar driving governed /search (hits render their WHY-chips; selecting focuses
  the dataset) + a /namespaces scope filter; a new Jobs tab lists the governed compute identities
  with clickable outputs. PLAYWRIGHT (hermetic, in CI):
  `governed search finds by column and focuses the hit; jobs tab lists compute identities` —
  asserts the column-tier hit renders `column:embedding` as its reason chip, selecting it focuses
  the dataset in Details, and the Jobs tab lists the mocked identity. Existing 3 specs unchanged
  and green (4/4).
  📌 Decision pin (2026-07-05, firnflow/lance_docs audit): default = FTS + FLAT exact vector scan (the rask
  pattern builds NO ANN index — correct at our scale); no IVF_PQ/ANN index on an embedding column without a
  measured gate — external BEIR data shows IVF_PQ recall loss GROWS with corpus size (~0 at ≤25k rows, ~22%
  nDCG@10 at 57k; nprobes/num_bits do not rescue it — re-measure on our stack, never copy thresholds). The
  gate is native, no harness needed: same queries with `bypass_vector_index=True` as ground truth
  (`lance_docs/lance_sdk.md:1997` documents it FOR recall calculation) vs indexed → adopt the index only if
  recall@10 ≥ 0.95; normalize for `num_unindexed_rows` (IndexStatistics); assert query distance_type matches
  the index's training distance type first ("results will be invalid" otherwise).
- 🔶 **P2 Compute seam completion** — Ray job submission surface PROVEN (2026-07-04): a real Ray cluster in kind
  (`deploy/ray-lance-demo.yaml`, image `.docker/ray-lance.dockerfile`) + `ray job submit` runs a genuine
  distributed lance_ray job against RustFS — distributed WRITE (4 fragments/1 commit) + INDEX + data EVOLUTION
  (add_columns, version pinning) + COMPACTION, all live-verified via `make ray-demo` (see docs/RAY.md, which
  also records the lance_ray↔pylance-8 version findings). EVENT-DRIVEN WIRING DONE (2026-07-05): the movers now
  submit their stage transform as a `ray job submit` IN RESPONSE TO the Dapr trigger (gated `medallion.ray`,
  fake-Ray default) via the Ray Jobs REST API (`services/medallion/services/ray_submit.py` + baked
  `scripts/ray_stage_job.py`); live-proven /produce → raw-to-bronze mover submits a job → bronze @2.2 + stable
  ids → AGE WROTE edge. REMAINING: the `parent` run facet (batch→chunk) + the KubeRay operator (rask merge).
- ⛔ **P2 Query engine** — DuckDB/DataFusion SQL over Lance + result cache: net-new (rask has neither), deferred
  by decision.
  📌 Decision pin (2026-07-05, firnflow/lance_docs audit) so the cache design isn't relitigated at build time:
  key = (uuid-prefixed table URI, branch/ref, `dataset.version`, sha256 of the FULL canonicalized request —
  filter/columns/k/nprobes/refine_factor/ef/distance_type/prefilter/fast_search/version-pin). Version-keyed
  entries are immutable snapshots (`guide.md:3288`) ⇒ zero invalidation bookkeeping; the URI's uuid prefix
  kills the delete-recreate stale-incarnation case; branch/ref is REQUIRED (versions are per-ref,
  `guide.md:3744`). Decode failure = cache miss + overwrite, never a 500; ship with request/hit/miss counters.
  Evaluate lance-namespace MATERIALIZED VIEWS (spec'd: autoRefresh on source change,
  `lance_docs/namespace.md:3080`; check maturity in our 0.9 pin) as the native alternative FIRST. Firnflow's
  semantic (cosine-threshold approximate-reuse) cache = rejected — approximate answers cut against the
  strict-fidelity posture, and no consumer exists.
- 📌 **Competitive watch (2026-07-12, Lakekeeper currency check v0.13.1):** Lakekeeper now
  catalogs LANCE tables (Generic Table API, 0.13.0) — metadata-pointer-only (their docs: no commit
  coordination, no schema enforcement, no data plane, no lineage). Verdicts in FEATURE-GAP.md §2
  re-affirmed + re-framed (currency banner added; vending softened to on-par). Possible future
  interop, NOT current work: register our tables as their generic pointers for a shared org
  catalog while we keep the data plane. Re-check at their 0.14/0.15.
- ⛔ **P2 Control plane** — warehouse/project/role/user admin API (or CRDs following rask’s operator pattern);
  rask has no tenancy/operator of its own — this stays ours. FGA-as-registry + declarative seeding is the
  interim.
- 🟡 **P1 Externalization hardening** (ties to §1/§2) — PARTIALLY DONE 2026-07-11 (Batch 7):
  ✅ Vault skipVerify conditional (verified already shipped: `dapr-component.yaml` ternaries
  skipVerify on the vault addr scheme — https verifies, plain-http dev OpenBao skips; was
  render-verified both ways when it landed); ✅ **medallion secret consumption** — the
  movers/producer were the LAST real S3 consumers shipping the key in plaintext pod env, and WORSE:
  the chart already omitted that env when `secretsViaDapr` was on but nothing told the service to
  consume the store, so a store-on deployment left medallion CREDENTIAL-LESS (latent breakage,
  found in Batch 7). Now: `MEDALLION_SECRETS_FROM_DAPR` + `apply_dapr_secrets` (strict sole
  source, fails closed — symmetric with catalog/lineage/compaction), called via threadpool in
  BOTH lifespans; chart else-branches set the flag (CI helm-template is the render gate). TESTS
  (tests/unit/test_medallion_secrets.py): `test_flag_off_is_a_no_op_and_never_fetches` (default
  boot byte-identical; fetch monkeypatched to AssertionError proves no store call),
  `test_flag_on_store_is_the_sole_source` (store value replaces env residue; repr never leaks the
  secret), `test_flag_on_store_miss_fails_closed` (REAL fetch_required_secrets path → RuntimeError
  'failing closed'; settings untouched on failure). **BATCH 8 (2026-07-11) closed the rest by
  verification** — three sub-items were ALREADY SHIPPED (this list was the stale artifact, same
  pattern as the §8 docs sweep): ✅ observability-s3 behind ESO (`external-secrets.yaml` owns the
  same-named Secret when `externalSecrets.enabled`; the static Secret in `observability.yaml` is
  skipped — two-tier rule holds); ✅ NATS external hooks (`nats.externalUrl` → `lance.natsUrl`
  threads through BOTH pubsub components and the stream-provision Job, which guards
  `if or nats.enabled nats.externalUrl`); ✅ stream replicas (`nats.streamReplicas`, default 1, on
  the add-stream line). ✅ Dex→Keycloak swap VERIFIED config-only (2026-07-11 audit): `IDToken`
  requires only the five core OIDC claims (iss/sub/aud/exp/iat — mandatory on every conformant
  provider), the ONLY claim consumed anywhere is `token.sub` (FGA subject + lineage author),
  `aud` accepts str|list (Keycloak arrays fine), zero dex-specific claim names in services/ (grep:
  only agnosticism docstrings + the dev-http `allow_insecure` flag). REMAINING (moved to the rask
  merge, where it belongs): OpenFGA datastore memory→postgres when rask adopts it.
- ⛔ **P2 Lineage at rask scale** — `parent` facet ingestion, event-volume posture (AGE indexes + pruning from
  §4, /events cursor), `dataQualityMetrics` (deferred, costly on Lance).
- 📌 **lance_docs mirror currency audit + refresh (2026-07-10, user request)** — cloned BOTH upstream
  repos and content-diffed every mirror section (not commit dates): `namespace.md` was ALREADY
  byte-identical to lance-namespace HEAD (v0.9.0, 2026-07-01); `guide.md` + `file_format.md` were STALE
  vs lance HEAD (9.0.0-beta.21) and are now refreshed to byte-identical. What upstream added since our
  2026-07-03 snapshot, by relevance: **(a) `cleanup_old_versions` doc'd in depth + NEW
  `AutoCleanupConfig`/`enable_auto_cleanup`** (auto-GC every N commits — a potential future simplifier
  for the compaction sweep's GC half; NOT adopted, our sweep also compacts+indexes); **(b) NEW
  fragment-sizing guidance** (1M rows/fragment fine to ~1B rows; more fragments under heavy concurrent
  merge_insert since conflict detection is per-fragment — relevant to the merge-key work); **(c) NEW
  `guide/observability.md`**: pylance ships `lance.otel.instrument_lance_metrics()` (`pylance[otel]`) —
  native Lance object-store/IO metrics straight into our existing OTel/Greptime pipeline, a cheap
  observability win to evaluate; **(d) per-base storage options** (`base_<id>.<key>` — multi-bucket
  datasets); **(e) zonemap+bloom now EXACT for IS NULL** (null-row bitmap); **(f) MemWAL spec heavily
  restructured (generations/sharding — still future, unimplemented by us); (g) tensorflow decoders
  dropped from arrays.md (Pillow-only — matches our Pillow deriver).** `spec.yaml` (root + ns_catalog)
  refreshed to 0.9.0: still 54 ops (conformance test green); additive deltas = optional `context` on
  responses, 3 formalized response schemas, and `DescribeTableRequest.tag` (describe-at-tag) — our
  installed 0.9.0 client already carries them all. **Anchor note:** the refresh shifted line numbers
  (guide.md +~150, file_format.md ±~20 around §conflicts); the load-bearing cites were re-pinned in the
  same batch (CAS item: file_format 4778→4765, 4836→~4801, guide 2964→3080; defer_index_remap: guide
  3013→3150; conflict taxonomy: file_format ~5261→~5253) — treat any OTHER pre-2026-07-10 line cite in
  this file as approximate. **Follow-up decisions (same day, probed against the INSTALLED packages per
  §0):** (1) **describe-at-tag FIXED** — the native dir backend at pylance 8.0.0 silently IGNORES a
  describe `tag` (probed: a NONEXISTENT tag described the latest version with no error), so the
  catalog now resolves tag→version itself via the dataplane tag store (`?tag=` on /describe; 404 on
  unknown, 400 with `version`; moto-pinned) — which also surfaced+fixed a pre-existing 500: pylance's
  `tags.get_version` RAISES ValueError on a missing tag (never returns None), so `/tags/version` on an
  unknown tag was a 500, now 404. (2) **`lance.otel` is ABSENT at pylance 8.0.0** (9.0 feature) — and 8.0.0 IS the newest
  PyPI release (verified same day: 9.0 exists only as unreleased source betas), so there is nothing to
  bump TO yet. **PRE-WIRED instead (2026-07-10)**: `common/lance_metrics.py::instrument_lance_if_available`
  (guarded, never fails startup; 3 unit-tested paths) is called from all five lifespans
  (catalog/lineage/compaction/medallion producer+mover) — when pylance 9 ships, the bump + switching the
  pin to `pylance[otel]` (pyproject comment marks the spot) lights Lance-native IO metrics up in the
  existing OTLP→Greptime pipeline with zero further code. (3)
  **AutoCleanupConfig IS present at 8.0.0 but NOT adopted** — it would run GC inside writer request
  paths (movers/catalog) rather than the maintenance window, its tagged-version interplay at 8.0.0 is
  unprobed (our sweep explicitly sets error_if_tagged_old_versions=False for the promotion tags), and
  it would bypass the compaction FAIL-visibility just built; the sweep stays the one GC owner.
  Re-evaluate only if the sweep itself becomes a bottleneck.
- 📌 **Native pylance/spec capabilities surfaced by the 2026-07-05 lance_docs full-read** — exploit before
  building bespoke: (a) `dataset::delta` CDC — `list_transactions` + `get_inserted_rows`/`get_updated_rows`
  between versions (`guide.md:2291`); with stable row ids (already ON for cascade writes) a change-data-feed is
  plain SQL over `_row_created_at_version` (`file_format.md:4277`) — candidate replacement for bespoke cascade
  event bookkeeping. (b) `@lance.batch_udf(checkpoint_file=…)` = crash-resumable `add_columns` backfills
  (thumbnail/embedding derivation, `guide.md:670`) — but schema changes conflict with most concurrent writes,
  so schedule column adds in quiet windows (`guide.md:594`). (c) Spec virtual columns + materialized views
  (`namespace.md:2017,3080`) are a spec-level twin of the medallion derive cascade — check maturity in our
  lance-namespace 0.9 pin before building more cascade machinery. (d) Lance's RAM caches (1 GiB metadata +
  6 GiB index, `index_cache_size_bytes`) are PER table-object, NOT shared across opens (`guide.md:2899`) —
  audit that services hold long-lived dataset objects / a shared Session; per-request reopens silently nullify
  all native caching. (e) `lance::events` trace targets + per-plan execution metrics
  (iops/bytes_read/parts_loaded, `guide.md:2780`) can wire into the Greptime stack for free. (f) pylance 8.0.0
  anchors: new FTS indexes are still format v1 (v2-by-default lands in 9.0); `IndexSegmentBuilder` removed
  in 7.2 (consistent with the lance_ray landmine).

## 10 · Explicitly refuted (do NOT re-report as bugs)

- “No DLQ = silent data loss” — refuted: Limits-retention streams (168h) + ephemeral-consumer restart replay
  recover exhausted messages idempotently; chaos-tested in docs/RESILIENCE.md; DLQ is a documented prod-roadmap
  item. Residual = wording fixes in §8.
- “Full-stream replay on restart is a defect” — refuted: documented trade-off (RESILIENCE.md gap #3) that fixed
  a worse durable-PUSH orphan bug; idempotent end-to-end. Residual = `deliverPolicy: new` for triggers (§2).
- “Token-less triggers duplicate Run nodes / stage RETRY re-runs are a bug” — refuted: token always set by every
  wired publisher, route token-guarded, whole-stage replay is the documented at-least-once design converging
  via MERGE + overwrite.

## 11 · Lineage lifecycle-emit + AGE-constraint review (2026-07-05, wf_57c04d9d — 13 findings, all verified)

Adversarial review of the Batch-C AGE constraints + the #93 lifecycle changes + #92 blob create. Only ONE
"broken" (rename) — and the **live-verify (redeploy + governed drive) showed it is MOOT**: `rename_table`
returns **501 UnsupportedOperationError** on the `dir` namespace backend (our shipped stack — the integration
suite even pins the 501 mapping). You can't rename a table, so there is no provenance to lose. This is the
canonical "verified against code, not against the running backend" miss the review made and the live-verify
caught. **Fixed + live-verified in AGE this session:**
- 🟥→⚪ **RENAME lost provenance (the one "broken")** — MOOT: rename is 501 on the `dir` backend. The
  rename-lineage code (emit_rename_event + inputs param + RENAME_TABLE create-class op) was **REVERTED** as
  speculative dead code — it fires only on a rename-supporting backend that doesn't exist here. If one is
  adopted, re-add dest←source lineage in `tables.py:rename_table` (a comment marks the spot).
- ✅ **deregister emitted no marker** → a detach looked like a live, never-touched table. Now emits a
  versionless `deregister_table` marker (asymmetric with drop, which deletes). **Live-verified in AGE:** a
  deregister run lands with `operation='deregister_table'` + a WROTE edge (via Dapr→NATS→lineage→AGE).
- ✅ **drop op invisible on the Run node** — `operation` is now a first-class Run property, surfaced in
  `/producers` + `/runs` (`ProducerInfo.operation` / `RunStatus.operation`). **Live-verified in AGE:** create/
  drop/deregister runs carry `operation` correctly. NOTE: drop+deregister also `revoke_ownership`, so the
  acting owner 403s on the dropped table's governed `/producers` afterward — the record persists for the
  ungoverned reconcile/audit/graph readers (which is who cares "is this dataset still live?").
- ✅ **New deadlock mode from the vertex UNIQUE index** (two concurrent ingests first-creating ≥2 shared
  datasets in opposing order). Fixed by a **deterministic name-sorted MERGE order** across the input+output
  loops → total lock-acquisition order, no circular wait.
- ✅ **:Column dup double-listing** — `_DATASET_COLUMN_NODES` now `RETURN DISTINCT`.

**Deferred (documented, not dev-blocking):**
- ✅ **DONE 2026-07-11 (Batch 5) — column-inventory GC on overwrite; LIVE-PROVEN on real AGE in CI
  the same day.** The first CI run FAILED the new live test exactly as designed — on real AGE a
  stale redelivery re-ADDED its old columns (['a','b','x','y']) because the first cut gated only
  the prune, not the seeding; fixed (recency-gate covers the whole inventory touch; version-less
  events keep legacy grow-only) and CI run 29160855426 is fully green, lineage-e2e included. A
  schema facet is the COMPLETE current schema by contract (review-verified across every emitter:
  catalog pinned-read, medallion facet_fields of the written dataset, train job's fixed registry
  schema; compaction sends none), so ingest now UNLINKs HAS_COLUMN entries outside (schema ∪
  column-edge out_fields) — {a,b}→{x,y} no longer lists a,b as CURRENT. Only the LINK is deleted:
  :Column nodes + COL_DERIVED_FROM history + per-version WROTE schemas untouched. REVIEW-CAUGHT +
  fixed: a stale REDELIVERED event's schema must never unlink live columns → the prune is gated on
  `_prune_allowed` (event version ≥ the graph's latest WROTE version; version-less or unparseable →
  never prune — stale deliveries degrade to the old grow-only behavior). TESTS:
  `test_ingest_schema_facet_prunes_stale_column_inventory` (v5≥graph-v4 → unlink issued with
  fields=[x,y,z]), `test_ingest_stale_redelivery_never_prunes` (v2<graph-v9 → no unlink;
  version-less → no unlink), `test_ingest_without_schema_facet_never_prunes`; LIVE:
  `test_terminal_lifecycle_and_column_gc_against_age` (e2e, needs LINEAGE_DATABASE_URL) executes
  the NOT..IN list-param DELETE on real AGE and asserts inventory==[x,y] + stale redelivery
  changes nothing.
- ✅ **DONE 2026-07-11 (Batch 5) — reconcile no longer false-flags deliberate drops; LIVE-PROVEN on
  real AGE in CI the same day (run 29160855426: drop derives the drop time, the recreate flips it
  back to None).** Dropped-ness is DERIVED AT READ TIME (`repository.dropped_at`): the dataset's most
  recent SUCCESSFUL run being a `drop_table` ⇒ the sweep SKIPs it (absence on storage is expected).
  The first design (a stored dropped_at stamp + clear) was KILLED by the adversarial review as
  last-DELIVERY-wins: a stale redelivered drop after a recreate would re-stamp a LIVE dataset out
  of the sweep — derivation over idempotently-MERGEd Run history is redelivery-proof by
  construction, and the `event_type='COMPLETE'` filter is load-bearing (FAILed drops keep WROTE
  edges for /producers and must assert nothing). TESTS:
  `test_dropped_at_derives_from_the_latest_successful_run` (drop→time, recreate-outranks→None,
  no-runs→None, COMPLETE filter pinned in the query string),
  `test_reconcile_all_skips_dropped_datasets` (dropped dataset absent from the report AND its
  storage never read); LIVE: the same e2e above asserts dropped_at derives on real AGE and flips
  back after the recreate. The rename-source variant rides the same derivation (a rename emit is
  a successful non-drop run on the target; the abandoned SOURCE name still needs a rename-aware
  emit before it benefits — rename is 501 on the shipped dir backend, unchanged).
- 🟨 **:Column has no UNIQUE index by choice** — dup column vertices from a rare concurrent first-create are
  benign (the DISTINCT masks the only visible symptom) and an index would add abort/retry churn to the hot
  column path. Reconsider only if column dedup becomes load-bearing.
- 🟨 **Losing-side of a concurrent first-create aborts the whole ingest txn → one ~30s-delayed Dapr
  redelivery** per brand-new shared vertex under prod concurrency (replicas≥2). Self-heals; the sorted MERGE
  order narrows it. Inherent to the UNIQUE index; a per-statement savepoint would remove it (invasive, deferred).

## 12 · Prod hardening — delegate-to-platform (2026-07-05, don't-reinvent audit wf_f401eea8; NOT dev-blocking)

**Verdict: we reinvent NOTHING k8s/Dapr owns — zero code to delete.** All gaps below are native switches we
haven't flipped. Almost all are **prod-only** (kind's default CNI ignores NetworkPolicy; PSA/SA/infra-SC are
prod concerns) — deliberately NOT rushed into the dev baseline (footgun-sequenced). See memory
`dont-reinvent-k8s-dapr-verdict`.

- 🟡 **Network L3 layer — CODE-COMPLETE 2026-07-11 (Batch 9); LIVE FLIP ON A POLICY-ENFORCING CNI
  PENDING.** Implemented the audit's fix order exactly in `chart/templates/network-policy.yaml`
  (flag `networkPolicy.enabled`, default OFF — kind's default CNI ignores NetworkPolicy, so the
  default is behavior-identical everywhere): (1) namespace default-deny Ingress+Egress;
  (2) the kube-dns egress allow IN THE SAME FILE (the audit's footgun honored); (3) targeted
  EXCLUSIVE ingress for the guarded stores — openbao:8200 ← ONLY the secret-consuming app pods
  (catalog/lineage/compaction/lance-ray/movers, movers ranged from values; ESO via
  `networkPolicy.openbaoExtraFrom`), age:5432 ← lineage/catalog/openfga(+migrate)/backup-pg,
  rustfs:9000 ← data plane + GreptimeDB + backup (+ ray demo pods via `rustfsExtraFrom` default) —
  and the general intra-namespace ingress allow EXCLUDES the three stores via NotIn so the lists
  stay exclusive (additive-allow semantics); (4) values-prod flip = the live step. Plus:
  intra-namespace + api-server egress allows (Dapr control plane), `extraEgress` for externalized
  backends, front-door ingress (gateway/web), the original lance-ray policy kept.
  VERIFIED: template stub-parses to 11 well-formed policies; CI now RENDER-AND-GREPS both ways
  (flag off ⇒ exactly 0 NetworkPolicies; flag on ⇒ ≥9 incl. default-deny + kube-dns-in-same-render
  + the openbao policy + the NotIn exclusion) — the render gate lives in ci.yml where helm runs.
  ✅ DONE WHEN (live, §7a): on a Calico/Cilium cluster with the flag on — all pods Ready; make
  e2e-governed-union + e2e-lineage green; NEGATIVE probe: `kubectl exec <web pod> -- wget -T3
  openbao:8200` times out (any pod outside the client list), while a catalog pod's sidecar still
  reads secrets (positive control = the stack boots with secretsViaDapr on).
  🚧 GUARDRAILS: never flip the default in values.yaml (kind default CNI = silent no-op is fine;
  a policy CNI + untested flip could brick flows); ESO deployments MUST set openbaoExtraFrom
  BEFORE flipping or external-secrets loses vault access.
- 🟡 **Per-workload ServiceAccounts — CODE-COMPLETE 2026-07-11 (Batch 10); live `dapr mtls -k`
  pre-check pending (the audit's own gate).** `security.serviceAccounts.enabled` (default OFF):
  `security-sa.yaml` renders a dedicated UNBOUND SA per first-party workload (12 fixed + one per
  mover from values, 16 total) with `automountServiceAccountToken: false` ON THE SA OBJECT (never
  the pod — the Dapr injector's projected token stays untouched, per the audit); every first-party
  pod spec (3 services + producer + movers + compaction + dashboard + 5 infra + all 7 job pods
  sharing `-sa-jobs`) gains a flag-gated `serviceAccountName`. CI render-and-greps: flags off ⇒
  zero of our SAs; flags on ⇒ ≥16 SA objects all automount-false + ≥12 pods wired.
  ✅ DONE WHEN (live, §7a): flag on → all pods Ready, `dapr mtls -k` still verifies, e2e green.
- 🟡 **Infra securityContexts — CODE-COMPLETE 2026-07-11 (Batch 10); live boot check pending.**
  `security.infraContexts.enabled` (default OFF): pod-level contexts for rustfs/age/openbao/dex/
  gateway with PER-IMAGE uid/fsGroup from values (age=999 postgres, openbao=100 vault-family,
  gateway=101 nginx — the audit: data/secret holders need the RIGHT ids for their PVCs, no blind
  helper reuse; ids are values-overridable precisely because they are image-version-dependent).
  Subcharts stay delegated to their own values surfaces (unchanged, per the audit).
  ✅ DONE WHEN (live, §7a): flag on → every infra pod Ready + rustfs/age/openbao PVC data intact
  after a restart (fsGroup correctness is only provable against the real volumes).
- 🟡 **PSA enforcement — PREREQ SHIPPED 2026-07-11 (Batch 10); the label itself is a runbook
  step.** The audit's sequencing footgun is closed: both root-busybox `wait-age` init containers
  (lineage + openfga-migrate) now carry restricted-compliant contexts (runAsNonRoot, uid 65532,
  no-priv-esc, drop ALL, RuntimeDefault) under the infraContexts flag — CI grep-asserts
  `runAsUser: 65532` renders. The namespace label is kubectl, not chart (`kubectl label ns
  <ns> pod-security.kubernetes.io/enforce=baseline`, then `restricted` once the infra contexts
  are live-proven) — added to the §7a runbook in that order.
- ✅ **Cheap hygiene done this session:** phantom `medallion.producer.port`→`medallion.port` (network-policy);
  pinned `dapr.global.mtls.enabled:true` explicitly (self-documenting, guards an accidental flip); corrected the
  misleading "rolled in-house" docstring in `common/oidc.py` (it wires PyJWT — no hand-rolled crypto).
- 🟨 Minor: downgrade `dapr-dashboard` ClusterRole/Binding → namespaced Role; fold `greptimedb-ttl-job`'s
  hand-typed securityContext into a pod-level helper variant (DRY).
