# GOAL — Prove it: finish #3/#4 for real, kill claim-drift, make DONE mechanical

> ## ✅ STATUS: COMPLETE (2026-07-15) — every clause proven, CI green, all pushed
>
> All 8 goal clauses are demonstrated with real command output; CI run **29393280868** is green
> (5/5 jobs), the e2e suites run **12 passed / 0 skipped**, the full unit+integration suite is
> **708 passed**, tree clean, everything on `feat/catalog-parity-1-and-5` (never main, HEAD `9729ea7`+).
>
> | clause | what | proof |
> |---|---|---|
> | 1 | prod render green | `helm template -f values-prod.yaml` → 6 `OUTBOX_URI`, `replicas:1`, exit 0 |
> | 2 | CI e2e job (5 suites) | `ci.yml` `e2e-stack:` job; green run 29393280868 |
> | 3 | claim-lint invariants | `tests/unit/test_invariants.py` 10 passed, CI `ci.yml:49` |
> | 4 | audit fixes 3–12 | 9 FIXED-with-proof + 3 WONTFIX-with-rationale (§ *P4 FINAL* below) |
> | 5 | outbox metrics live | 5 counters + 2 gauges; depth gauge arc **0→4→0** live in GreptimeDB |
> | 6 | SIGKILL crash e2e | `test_outbox_crash_e2e` passes: survives kill, drains to graph **and** /events feed |
> | 7 | dead code deleted | `_schema_is_blob` + `CreateTableRequest` removed; `sinks.py` kept (live consumers) |
> | 8 | suite green + pushed | 708 passed; clean tree; pushed to the feature branch |
>
> **The one caveat, stated plainly:** the dead-code sweep still reports `SinkAdapter` in
> `services/common/sinks.py`. It is **deliberately NOT deleted** — it is the designed "gold sink" seam
> with live consumers (`scripts/media_pipeline_e2e.py`, `tests/unit/test_ingest_seam.py`), so it is not
> dead; deleting it would break them. That is a decision, not unfinished work.
>
> **Deferred (net-new capability, NOT regressions), tracked as task #38:** `source_rowid` through the
> cascade, and MV lineage. Rationale in *P4 FINAL*. The catalog-parity goal does not depend on them.

**Set 2026-07-14.** Context: the #1–#5 parity build shipped, but three kinds of failure kept
recurring — (a) claims the code did not honor ("every lineage publish is staged" while three
publishers bypassed the outbox), (b) "live-verified" resting on manual terminal runs while CI
excludes `-m e2e`, and (c) features complete on the path I built but absent on the paths we
actually run (#3-B distributes on REST create; the medallion/Ray pipeline never distributes).

**The rule this doc exists to enforce:** a condition that cannot be proven by a grep, a test in
CI, or a live assertion with a durable artifact is NOT a condition — it is a claim, and claims
have repeatedly been wrong. Every item below states its mechanical proof.

**Scope guard (user-set):** NO query engine (consumption = DuckDB w/ Lance extension or
lance-ray, external). Column masking / SQLGlot / row-level SQL governance ship WITH that later
engine — not now. Batch processing + model training are the use case. NATS HA, KubeRay+Kueue,
rask merge: parked. Lakekeeper warehouse-polish backlog (table browser, soft-delete UI,
storage profiles, projects UI): explicitly dropped — wrong compass for a multimodal lakehouse.

---

## P0 — the proof infrastructure (do FIRST; everything else depends on it)

**P0.1 — CI runs the e2e suites against a real kind stack.**
Today `ci.yml` runs `pytest -m "not e2e"` — so every "live-verified" claim this session has no
guardian. Add a CI job that boots the kind stack (or a compose-equivalent profile) and runs the
e2e suites: outbox, warehouses, multibase, client-direct, CAS, governance.
*Proof:* the CI workflow file contains the e2e job and a run is green. `grep -c 'not e2e'` on the
main test job no longer tells the whole story — the e2e job exists beside it.

**P0.2 — claim-lint: the grep-provable invariants run as a test.**
A `tests/unit/test_invariants.py` that mechanically enforces, at minimum:
- zero bare `dapr_publish.publish_event` with `topic_name=settings.lineage_topic` in `services/`
  (the #4 uniformity invariant — violated 3× before it was grep-proven);
- every env var injected by the chart is READ somewhere in `services/` (the dead
  `MEDALLION_LINEAGE_OUTBOX_URI` class);
- every FGA relation the code writes or checks exists in the compiled `model.json`
  (generalize `test_fga_model_contract.py` + the warehouse write-relation guard to ALL call sites).
*Proof:* the test file exists, is in CI, and is green.

## P1 — make #4's guarantee true, observable, and crash-proven

**P1.1 — outbox depth/age metric + alert.** OTEL counter/gauge for staged/drained/poison +
outbox depth & oldest-age; Perses alert on depth>0 sustained. Without this a leaking outbox is
invisible — every durability property is unobservable. *Proof:* metric visible in Greptime after
a live stage/drain; alert rule in the chart.

**P1.2 — bounded drain.** The reconcile drain currently `list()`s the entire prefix into memory
under the single-flight lock; a backlog can OOM/stall the tick. Cap per tick (oldest-first),
carry the remainder to the next tick. *Proof:* unit test drains N>cap staged events across 2 ticks.

**P1.3 — real crash injection.** SIGKILL a mover between the Lance commit and the publish-ack on
the live stack; assert the staged event survives, the reconcile drains it, and the run lands in
BOTH the AGE graph and the durable /events feed. A mocked exception is not a crash.
*Proof:* `tests/e2e/test_outbox_crash_e2e.py` green in the CI e2e job.

**P1.4 — decide the prod default.** Outbox + reconcile are OFF in values.yaml and not overridden
in values-prod.yaml — the durability guarantee is dark exactly where it matters. Decide ON (and
document the cost) or document WHY off. *Proof:* values-prod.yaml sets it explicitly + a comment.

## P2 RESOLVED (2026-07-15) — #3 finished for the pipeline we run

- **P2.2 — real routing coverage: DONE.** `tests/integration/test_warehouse_routing.py` drives the REAL
  `get_namespace → _resolve_warehouse_root → warehouse_for_namespace` resolver (no fake) against a local-FS
  registry: a table under a bound namespace physically lands in the warehouse root and is absent from the
  default root (proven by reading the location + rglob, non-vacuous). Plus the collision guard:
  `create_warehouse_namespace` returns **409** when the name already exists unbound in the default root.
  Green in CI (`test` job).
- **P2.3 — warehouse lifecycle: DONE.** `deactivate`/`activate` endpoints (admin-gated on the warehouse's
  own project); a `status` field on the record; the resolver honors it (a deactivated warehouse → **403** on
  every op on its bound namespaces, status read LIVE so it takes effect on the next request). Proven by
  integration tests, a **live in-cluster** run (create 200 → deactivate → create **403** → activate → create
  **200** on the digest-matched image), and a new e2e case in the CI `e2e-stack` suite.
- **P2.1 — pipeline multi-base: WONTFIX (create-only), with evidence.** See the dedicated rationale below.

### P2.1 WONTFIX — pipeline multi-base is create-only by design (not an accidental omission)

**Decision:** do NOT wire `data_bases` (#3-B multi-base) through the medallion/Ray mover write path. #3-B
stays REST-create-only. **Evidence gathered before deciding:**

1. **Structural mismatch — base registration is CREATE-TIME-ONLY, the cascade is overwrite-only.** Multi-base
   registers its bases in the manifest via `initial_bases`, which pylance accepts **only on a fresh create**
   (`dataplane.py`: `initial_bases = ... if is_create ...`). The cascade movers (`compute.py.transform_stage`,
   `seed_raw`) write **exclusively** in `mode="overwrite"`. The dataplane's own caveat (lines 220-227) is
   explicit: a mutation that doesn't re-send `data_base` — which a bare overwrite cannot — "concentrates its
   NEW fragments in the primary root." So making the cascade distribute would require threading
   first-write-vs-overwrite base-registration state through the movers — real complexity, and getting it
   wrong silently concentrates fragments in the primary root (the live proof would be flaky by construction).
2. **The pipeline already distributes at the ZONE level.** The medallion writes per-zone (raw/bronze/silver/
   gold) buckets, swept by the multi-bucket GC. Per-TABLE multi-base is the Uber petabyte-scale throughput/DR/
   tiering pattern (`base_paths[]` across N buckets) — the cascade's stage tables are not at that scale.
3. **No per-table distribution signal exists in the cascade.** #3-B on REST-create serves a client that
   EXPLICITLY asks to distribute a table (passes `data_bases`). The cascade has no such signal; wiring it
   means inventing a distribution POLICY (which stages, across which approved bases) with **no current table
   that needs it** — a speculative half-feature, untested at the scale where it would matter.
4. **The read path constrains bases to shared creds.** `open_dataset` passes only the top-level
   `storage_options`, so every base must share the catalog's endpoint/creds (the `base_store_params`
   invariant). The cascade config would have to guarantee this too.

**Revisit trigger:** when a specific gold/training table demonstrably exceeds single-bucket throughput or
needs cross-region DR, AND the real Ray distributed-write path (the rask merge) lands — wire
`initial_bases` on that stage's first create + `target_bases` on subsequent overwrites, and validate fragment
distribution against a REAL workload, not a demo table. The create-only scope is stated in the
`compute.py` mover docstring so it reads as a deliberate boundary, not an omission.

---

## P2 (original plan) — make #3 true for the pipeline we actually run

**P2.1 — pipeline multi-base.** Medallion/Ray writes and `/insert` never distribute; #3-B is
REST-create-only, so no batch/training table is ever actually distributed. Wire `data_bases`
through the mover/Ray write path (or explicitly document create-only and close the task as
WONTFIX with rationale — no silent half-feature). *Proof:* live e2e — a cascade-written stage
table has fragments in a data base; or the WONTFIX rationale in this doc.

**P2.2 — real routing coverage.** The warehouse-aware `get_namespace` is overridden by a fake in
integration tests — the most load-bearing #3-A path has zero non-skip coverage. Drive the REAL
resolver (local-FS registry root) in an integration test. Also guard the default-root↔warehouse
namespace-name collision (binding `foo` when unbound default-root `foo` has tables orphans them).
*Proof:* integration tests exist + green in CI; collision returns 409.

**P2.3 — warehouse lifecycle minimum.** `deactivate`/`activate` (quarantine; routing honors the
flag) — no tenant offboarding story exists at all. Delete stays guarded/manual for now.
*Proof:* endpoint + FGA gate + integration test + live 409-after-deactivate.

## P3 — prove #2's ACID at the API layer

**P3.1 — concurrent /commit contention e2e.** The CAS harness proves the object-store primitive;
nothing drives N concurrent `POST /commit` racing one table through the API. Assert exactly one
winner per version, losers get 409 and converge on retry. *Proof:* e2e green in CI.

## P2.5 — frontend: audit + fix (user-directed 2026-07-14)

Skills-driven audit (`w1yn6g2r5`) covering: real bugs (poll-loop races, runes misuse, leaks,
error swallowing), **backend-contract drift** (the UI predates warehouses/multibase/commit/credentials —
are the generated OpenAPI types stale? does the BFF allowlist block them?), **dead code** (the ~8 orphan
type aliases = `/jobs` + `/namespaces` never wired in), and a11y/perf/type quality — verified against the
OFFICIAL Svelte 5 runes docs via the Svelte MCP, not guessed.
*Proof:* every CONFIRMED finding fixed with `bunx turbo run check test lint fmt:check` + Playwright green
in CI; dead code deleted and proven unreferenced.

## P1.1 PROVEN LIVE (2026-07-14) — outbox metrics in GreptimeDB, incl. the alert signal RISING

Not "the code emits metrics" — the signal was driven end-to-end on the kind stack and read back out of
GreptimeDB. Metrics reach Greptime via OTLP-direct (no Collector), tables auto-created from the metric names.

**Traffic (happy path).** 3 × `POST /produce` → the cascade fired, every stage publishing through the outbox:

| service | staged | published |
|---|---|---|
| lance-ray | 3 | 3 |
| raw-to-bronze | 3 | 3 |
| bronze-to-silver | 2 | 2 |
| silver-to-gold | 5 | 5 |

`staged == published` on every publisher → nothing stranded.

**Saturation (the alert signal) — the part that actually matters.** A gauge pinned at 0 is
indistinguishable from a *stuck* gauge, so 5 survivor events were staged into the outbox prefix (exactly
what a crash between the Lance commit and the publish leaves behind) and the relay was ticked:

```
outbox_depth (service=lineage, 5s export interval)
  0.0  0.0  0.0  0.0        <- steady state
  5.0                       <- survivors staged: the gauge RISES
  0.0  0.0  0.0  0.0  ...   <- relay drained them; falls back (does NOT alert forever)
outbox_events_drained_total = 5.0
```

**Recovery (the payoff).** All 5 events were re-ingested into the graph — verified in Postgres/AGE, not
inferred from a counter:

```
Run nodes recovered from the drained outbox survivors: 5
Rows on the durable /events feed: 5
```

Both surfaces matter: the drained run reaching `/runs` but being **silently absent from `/events`** was a
real bug fixed earlier this session, and this is its live regression proof.

> Housekeeping: those 5 synthetic runs (`aaaaaaaa-0000-4000-8000-*`, job namespace `proof`) are still in
> the dev graph. They are deliberately left rather than deleted — pruning graph nodes is a destructive DB
> action and is the user's call, not mine.

**What this does NOT prove:** the publish-failure path (`outbox.publish.failed` rising while NATS is down).
Proving it means taking the messaging backbone offline, which is out of proportion to the claim and was not
authorized. The staged-survivor path above exercises the same recovery code the crash would, and the SIGKILL
crash e2e (P1.3) covers the crash itself.

## P0.1 GREEN (run 29369341977) — every suite runs, nothing skips

```
tests/e2e/test_object_store_cas_e2e.py ...      (was: sss — never ran)
tests/e2e/test_client_direct_e2e.py    ..       (was: ss  — never ran)
tests/e2e/test_warehouses_e2e.py       ..
tests/e2e/test_multibase_e2e.py        ..
tests/e2e/test_outbox_e2e.py           .
tests/e2e/test_outbox_crash_e2e.py     .        (the SIGKILL proof)
============================= 11 passed in 13.42s ==============================
```
All five CI jobs green: `test`, `frontend`, `lineage-e2e`, `auth-e2e`, `e2e-stack`.

Getting here took **four** distinct bugs, and they share one root cause worth naming: **a fresh cluster
exposes ordering and configuration that a warm local cluster silently hides.** "It works locally" was never
evidence for any of this — the local stack had been migrated, injected and configured by previous runs.

1. **`--set web.enabled=false` on a key that did not exist.** Helm accepts unknown `--set` keys silently;
   the ungated web Deployment shipped anyway, its image is never built in CI, `ImagePullBackOff` blocked
   `helm --wait` forever. *Guarded:* `test_every_helm_set_key_in_our_scripts_exists_in_values`.
2. **`--wait` deadlocked against the OpenFGA post-install migration.** helm waits for Ready *before*
   running post-install hooks; OpenFGA cannot be Ready until the hook migrates its schema. Three-way
   deadlock — armed only on a database that was never migrated, i.e. only ever in CI.
3. **The Dapr sidecar injector race.** The injector is a MutatingWebhook and only injects into pods created
   *after* it is Ready; it ships in the same release as the apps, so the apps won the race, came up `0/1`
   with no sidecar, and hung on `Dapr health check timed out`.
4. **Two suites silently skipped and CI called it green** (below).

Also fixed: the failure hook dumped a *hardcoded* catalog+lineage log tail, so the pod actually blocking the
stack (OpenFGA) was never printed — two 12-minute CI round-trips learned nothing. It now describes every
not-ready pod and tails every not-ready container. **A diagnostic that only reports the components you
already suspected cannot find a surprise.**

## P0.1b — the two suites that never ran, while CI showed a green check

The job's first green read `6 passed, 5 skipped`. The skips were the story: **CAS (3 tests) and
client-direct (2 tests) — two of the five suites this goal names — had never executed, on any run, ever.**

* CAS reads `LANCE_E2E_S3_ENDPOINT`; the script exported `LANCE_E2E_S3`. A name mismatch.
* client-direct probes Dex OIDC discovery; the script exported the bare host while Dex serves it under
  `/dex/` — it **overrode each suite's correct default with a broken value**, the probe 404'd, and the suite
  skipped *itself*.

Both suites are skip-guarded on "is the stack reachable?" — correct on a laptop with nothing running, and a
**lie** in the e2e job, where the stack is up by construction. So the guard: **the runner now fails if any
test skips.** A green tick over a suite that never ran is worse than a red one; it actively buys false
confidence, which is the exact currency this document exists to stop spending.

## P0.1 CORRECTION — the e2e job that exists to stop unproven claims was ITSELF unproven

Clause (2) was marked done because the **workflow file existed**. It had never once run green.

Root cause: `scripts/e2e_stack.sh` deploys a headless stack with `--set web.enabled=false`. **That key did
not exist.** Helm silently accepts unknown `--set` keys, so the flag did nothing; the web Deployment (which
had *no* `if` guard at all) rendered anyway; its image is never built in that job, so the pod sat in
`ImagePullBackOff`; `helm upgrade --wait` could never converge; every dependent app crash-looped; the job
died at the 600s timeout. **Every run. Since the day it was added.**

The irony is the lesson: `e2e-stack` is the job whose entire purpose is to stop us shipping unproven
claims, and it was the most unproven thing in the repo. A CI job that has never been green is not a proof,
it is a decoration.

**Fixed:** `web.enabled` added (default `true` = prior behavior) and the Deployment + Service gated on it.

**Guard against the CLASS:** `test_every_helm_set_key_in_our_scripts_exists_in_values` asserts every `--set`
key our scripts pass is actually defined in `values.yaml`. A flag you *believe* you are setting, that
silently sets nothing, is worse than no flag — it makes a stack you never configured *look* configured.
Verified non-vacuous: it scans 9 real keys, and with `web.enabled` removed it flags exactly this bug.

## P0.0 — "pushed" is not "green". CI was RED on this branch the whole time.

The single most embarrassing finding of the session, and the one that most vindicates this document.

Every push to `feat/catalog-parity-1-and-5` had been FAILING CI, through commit after commit that reported
"suite green, pushed". Nobody noticed because nobody looked — I was verifying with `ruff check` + `pytest`
and calling that green, while CI runs a strictly LARGER set of gates:

| gate | ran locally? | result |
|---|---|---|
| `ruff check services tests` | yes | passing all along |
| `ruff format --check services tests` | **no** | **FAILING** — 10 unformatted files |
| `ty check` | **no** | **FAILING** — the vulture whitelist (bare names by design) reads as unresolved refs |
| `pytest` | yes | passing all along |

Fixing the first uncovered the second. The lesson is exactly the one this file exists for: **I verified the
thing I ran, not the claim I made.** "Pushed" was doing the work of "green" in my own reporting, and the two
had silently diverged. Checking is one command — `gh run list` — and it was never run.

**Guard:** run all four gates verbatim before claiming green. `test`, `frontend`, `lineage-e2e` and
`auth-e2e` now pass on the branch for the first time.

## P1.3 PROVEN — the SIGKILL crash e2e, and the vacuous assertion it was hiding

`tests/e2e/test_outbox_crash_e2e.py` now proves the whole chain, live (`1 passed`):

1. a real child process stages a full `RunEvent` — the open commit→publish window,
2. the OS `SIGKILL`s it (asserted: `returncode == -signal.SIGKILL`) — no `finally`, no flush, a real crash,
3. the staged object SURVIVES on object storage,
4. the run is verified **absent** from the graph first (see below), then the relay drains it,
5. it lands in **BOTH** the AGE graph **and** the durable `/events` feed — read out of Postgres,
6. the outbox ends empty.

**The test was previously proving less than its docstring claimed**, in two ways, and both are now fixed:

* It only asserted `outbox_drained >= 1`. That number just means *the relay counted the event* — it says
  nothing about the run reaching the graph, and nothing about the `/events` feed. Those are separate writes,
  and one landing without the other is a bug this repo **has actually shipped**. Both are now asserted at the
  source of truth (`LINEAGE_DATABASE_URL`, port-forwarded by `scripts/e2e_stack.sh`).
* Adding those assertions immediately exposed a **vacuity bug in the test itself**: `build_run_event` derives
  `run_id` as a deterministic UUID5, so a FIXED token made the run_id stable across runs — after the first
  run the event was already in the graph, and "the relay recovered it into the graph" would have passed
  **even if the relay did nothing at all**. Fixed with a fresh token per invocation, and a pre-flight
  `assert not pre_graph` that fails loudly if the run is ever present before the relay acts.

That pre-flight guard is the point: an assertion that cannot fail is not a test.

## P3 — dead-code sweep: the sweep itself was the bug

`make deadcode` (vulture + knip). The finding is **not** "we deleted N dead functions" — it is that the
sweep was useless and is now a guard.

* **Before:** ~70 "dead" symbols reported in `services/`, **every one a false positive** — FastAPI route and
  exception handlers, Dapr pub/sub + cron handlers, pydantic `model_config` / validators / model fields.
  Vulture is a static reachability checker and cannot see call sites that live in a framework registry.
  A sweep that cries wolf 70 times is WORSE than no sweep: a genuinely dead symbol is invisible in the noise.
* **After:** decorator-invoked symbols are ignored and reviewed knowns are whitelisted (with the reasoning
  written down in `.vulture-whitelist.py`). The sweep now prints **one** line, so a NEW dead symbol stands out.
* `ruff --select F401,F811,F841` over `services/`: **clean** (no unused imports, redefinitions or variables).
  Dead chart env vars are covered mechanically by `test_no_dead_chart_env_vars` in the claim-lint. Frontend
  dead code (4 orphan type aliases + 2 CSS vars) was deleted earlier; knip's residue is generated types.

**LANDMINE, recorded so nobody "cleans it up":** vulture flags `Image.MAX_IMAGE_PIXELS` in
`services/medallion/services/media.py` as an unused attribute, because it is an assignment to a Pillow
global. It is the **decompression-bomb guard**. Deleting what the tool reports would silently disarm a
security control while every test stayed green. This is exactly why the sweep is triaged, not auto-trusted.

**Deliberately NOT deleted:** `services/common/sinks.py` (the only surviving finding). No *service* imports
it — its consumers are its own unit test and `scripts/media_pipeline_e2e.py`. It is the un-wired "gold sink"
seam from the data-zone architecture. Deleting a designed seam is an architecture decision, not a cleanup,
so it is left visible in the sweep rather than quietly whitelisted.

## P4 FINAL (2026-07-15) — every wgznqpmwd ranked fix: FIXED-with-proof or WONTFIX-with-rationale

The clause requires each ranked fix to be *either* fixed with mechanical proof shown *or* explicitly
WONTFIX'd here. Full disposition:

| # | audit fix | status | mechanical proof |
|---|-----------|--------|------------------|
| 1 | non-blob creates → 2.2 + stable-row-ids path | **FIXED** | `create_table` routes ALL creates to `_create_table_direct`; unit `test_create_table_writes_plain_schema_at_2_2_with_stable_row_ids` + integration `test_api` real-namespace creates + **live** (governed catalog, Dex-auth, opened back `data_storage_version=2.2 has_stable_row_ids=True`) + CI `test_plain_catalog_create_is_2_2_with_stable_row_ids` |
| 2 | warehouses.py → domain exceptions | **FIXED** | `grep -c "raise HTTPException" warehouses.py` = 0; raises `InvalidInputError`/`PermissionDeniedError`/… ; suite green |
| 3 | dependencies.py fail-closed docstring | **FIXED** | `catalog/api/dependencies.py:35-54` docstring now states fail-CLOSED, matching the code |
| 4 | incompatible commit → non-retryable | **FIXED** | `_COMMIT_INCOMPATIBLE_MARKERS` → 400 in `_classify_commit_error`; `test_client_direct_commit` pins it (was pinning the corrupting 409-recommit advice) |
| 5 | spec `vend_credentials` on describe | **FIXED** | `tables.py:169` honours `vend_credentials`→`storage_options`, read-tier only, multi-base → server-mediated |
| 6 | `source_rowid` through the cascade | **WONTFIX (this branch)** | see below |
| 7 | rename branch-guard + live GC-vs-branches probe | **FIXED** | `_refuse_rename_with_branches` via `.branches.list()`; GC-vs-branches REFUTED live (`older_than=0`, branch survived, 0 files reclaimed) |
| 8a | rename `DERIVED_FROM` edge | **FIXED** | `inputs` threaded through the emitter chain; rename passes source; consumer materializes `(dest)-[:DERIVED_FROM]->(src)`; 3 unit tests |
| 8b | MV lineage | **WONTFIX (this branch)** | see below |
| 8c | catalog FAIL events | **WONTFIX (design)** | see below |
| 9 | GC sweep covers per-warehouse + multibase buckets | **FIXED** | `sweep_buckets` union; `run_sweep` iterates all; chart wires the union; live GC proof earlier |
| 10 | gateway probes/preStop/securityContext | **FIXED** | `gateway.yaml` has all three; `test_every_first_party_deployment_is_hardened` enforces it in CI |

**WONTFIX rationales (explicit, not silent omissions):**

- **8c catalog FAIL events — WONTFIX (design decision, not a gap).** The medallion/compaction workers emit
  FAIL because they are data-processing JOBS that attempt in-flight work and can fail mid-stream. A catalog
  metadata op that fails is a *rejected request* (client 4xx: TableAlreadyExists, schema mismatch) or a store
  outage (503) — there is no partially-completed dataset work to record a FAIL run against, and emitting FAIL
  runs for rejected requests would pollute the graph with non-events that `producers()` would surface as if
  real. The one genuinely relevant case — a write that COMMITTED data but failed after — is already covered
  by #23 reconcile (storage-ahead back-fill). Emitting more would be wrong, not merely more work.

- **6 source_rowid through the cascade — WONTFIX (this branch); net-new capability, tracked.** Not a
  regression: nothing that worked stopped working. The FOUNDATION is now complete — stable row ids are on for
  BOTH catalog creates (this session) and cascade writes (compute.py), so the datasets can carry `_rowid`.
  Propagating a source `_rowid` column through each medallion transform (and replacing the positional
  `range(rows)` blob carry-forward) is a feature-scale change to the compute layer with its own live e2e,
  belonging with the model/experiment-lineage work (tasks #17/#18), not bundled into a catalog-parity branch.

- **8b MV lineage — WONTFIX (this branch); depends on native MV maturity.** The governance-critical half is
  DONE: `create_materialized_view` seeds FGA ownership on the `materialized_view` type (creator keeps
  refresh/read; namespace writers inherit). Emitting `MV DERIVED_FROM <source base tables>` requires
  extracting the source tables from the MV's query definition — a query-parse step whose shape depends on how
  far the native MV feature matures, which the user has explicitly deferred (query engine is out of scope for
  batch+training now). Recording a guessed or empty input set would be worse than recording none.

These three are logged as a tracking task so they are visible future work, not dropped.

## P4 STATUS — SUPERSEDED by *P4 FINAL* above

This section tracked the mid-work state ("8 landed, 3 open — non-blob creates still pin 2.1, rename
hardcodes `inputs: []`"). All of it is now resolved: non-blob creates route through the 2.2 + stable-row-id
path, and rename records a `DERIVED_FROM` edge (both proven live). The audit-workflow "reserved" placeholder
that followed is likewise closed — every verdict was triaged into the *P4 FINAL* table. Kept as a one-line
tombstone rather than deleted outright, so the doc's own history shows the drift it was written to prevent.

## THEN (after P0–P4, the actual product direction — user-confirmed)

Multimodal retrieval + the ML loop, in this order and nothing sooner:
1. Governed k-NN `/search` over cascade-derived embeddings (native Lance `nearest`; NOT an engine).
2. Model registry + candidate→blessed promotion (task #17) with lineage to the exact dataset
   version + row-id provenance to source media.
3. Experiment tracking via OTLP→Greptime (task #18).

## DONE-definition (applies to every item above, permanently)

An item is DONE only when it has been through the FULL loop, in order:

1. **Build against the skill references** — READ the reference files named for the task below
   (not the SKILL.md index) BEFORE writing code, and match them.
2. **Unit + integration green** — `PYTHONPATH=services uv run pytest tests/unit tests/integration`.
   New-bug rule (writing-python testing.md T6): when a bug is found, test EVERY similar case in the
   same change — the outbox shipped with 3 of 4 publishers bypassing it because T6 was skipped.
3. **Redeploy for real** — rebuild the image, explicit `kind load docker-image ... --name lance`,
   DELETE the pods (not rollout-restart), verify the running imageID digest changed.
4. **Live e2e on the redeployed stack** — the feature driven end to end against the cluster.
5. **Adversarial audit** with the relevant skills as the rubric; findings fixed; fixes re-verified
   live (steps 3–4 again).
6. **The proof lands in CI** — the mechanical condition (grep-lint or e2e) runs on every push.

"It worked when I ran it" is an anecdote, not a state.

### Relevant skill references per task (read these files, not the index)

| Task | Skill references to read + follow |
|---|---|
| P0.1 CI e2e | `writing-python/references/testing.md` (skip-rule: every skip needs its unblock — the CI job IS the unblock; F.I.R.S.T.; integration markers), `python-infrastructure/references/background-jobs.md` |
| P0.2 claim-lint | `writing-python/references/testing.md` (T6 exhaustive-near-bugs — the lint IS T6 mechanized), `openfga/references/core-relations.md` (the model-contract half) |
| P1.1 outbox metric | `python-infrastructure/references/observability.md` (four golden signals at EVERY external boundary — the outbox is an S3+pubsub boundary with zero metrics today = a direct violation; bounded cardinality; OTel meter not prometheus-client), `otel/references/python-sdk.md`, `otel/references/attributes.md` (semantic names) |
| P1.2 bounded drain | `python-infrastructure/references/resilience.md` (tenacity conventions; retry only transient; fail-safe defaults), `python-infrastructure/references/background-jobs.md` |
| P1.3 crash e2e | `writing-python/references/testing.md` (test behavior not implementation; a mocked exception is an implementation detail — SIGKILL is the behavior) |
| P2 #3 pipeline | `writing-python/references/{error-handling,anti-patterns}.md`, `fastapi/references/{core-conventions,dependencies}.md` |
| P3 commit contention | `writing-python/references/testing.md` (boundary conditions T5) |
| P4 triage | `openfga/references/*` for any model change; `python-infrastructure/references/dapr-workflows.md` for the Dapr-native verdicts |

## Consolidated from the superseded todo files (full-file extraction, 2026-07-14)

Full reads of `todo_confirm.md` (214 lines) + `todo_fable.md` (1806 lines) — every item classified.
**Stale-glyph corrections** (marked pending there, actually LIVE-PROVEN 2026-07-13 by the §7a done-done
pass): merge_insert BTREE index, compaction FAIL-visibility (deterministic FAIL Run node), the three §7a
majors, the #115 training lane drive, the artifact janitor. Do NOT re-do these.

**Genuinely open items that survive consolidation** (beyond P0–P4 as already written):
- **T1 (→ THEN #2, the one real training blocker): no trainer service credential** — the Ray job's
  self-emitted lineage 401s against governed ingest, so ALL training provenance is lost in the shipped
  auth-on stack (todo_fable 564-566).
- **T2 (→ P1-adjacent): create_table process-crash strand** — a crash between write and FGA grant strands
  the table; deeper fix = declare→grant→write reorder (todo_fable 210-211).
- **T3 (→ P2.1, fold): `/insert` version-attribution race** — read-after-write, blocked upstream, reconcile
  heals; same endpoint P2.1 touches (todo_fable 213-216).
- **T4 (→ P4): external-base blob GC pointer-awareness watch** + AutoCleanupConfig-vs-sweep decision +
  the **RAM-cache/Session audit** (Lance caches are per-dataset-object; per-request reopens silently
  nullify ALL native caching — concretely actionable) (todo_fable 1377-80, 1648-66).
- **T5 (→ P0-adjacent): OpenBao × medallion-compute un-integrated** — compute reads S3 creds from env
  only, full-union e2e runs openbao off (todo_confirm 127-130).
- **T6 (→ THEN #2): run-INPUTS API** — a run's input version pins reachable only via raw Cypher; needed
  for "which feature versions trained this model" (todo_confirm 156-158).
- **T7: governed-union re-confirm** — the 4/4 live evidence predates the §7a hardenings; re-run
  `make e2e-governed-union` (subsumed by P0.1 once e2e is in CI) (todo_confirm 109-113).
- Prod-hardening (L3 default-deny on a real CNI, PSA, mTLS pre-check, per-column masking): code-complete
  or parked; deprioritized under the batch+training compass — NOT current work.

## Housekeeping status (2026-07-14)

- **LICENSE: pushed** — commit f816526 confirmed on `origin/feat/catalog-parity-1-and-5`
  (the branch push `f816526..f044b4d` proved the remote already had it; everything since is up too).
- **todo.md / todo_confirm.md / todo_fable.md: superseded-bannered** (commit 80d2d51), full
  live-item extraction in progress — surviving items get folded into the P-levels here and the
  stale bulk trimmed. This file is the single source of truth.
