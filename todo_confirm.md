# todo_confirm — the "don't miss a thing" verification matrix

One row per pillar-claim: what is **CONFIRMED live** (with the exact evidence + the command that
re-proves it), what is confirmed **WITH A CAVEAT**, and what is still **OPEN**. This is the checklist
for "is the lakehouse actually working as intended", kept honest per the §0 rule: *"tested" means
driven in the shipped combination, not unit-passed.* Update a row only with transcript evidence.

Legend: ✅ confirmed live · 🟡 confirmed with a named caveat · ⛔ open (not yet true / not yet proven)

> **2026-07-13 — FULL KIND-RUNBOOK PASS RUN. Read `todo_fable.md` §7a for the complete verdict.**
> Both e2e suites green on the union stack; every 🟡 "code-complete, live pending" row below is now
> driven. The pass found **six live-only bugs** (all fixed + re-proven): the web image never booted;
> durable-consumer config drift silently kills all delivery for ~25 min on a config-changing upgrade;
> **the trainer's FGA gate was dead (a revoked trainer still trained)**; a `TOKEN` env collision with
> lance's AWS-session-token fallback made training 100% broken; `MEDALLION_RAY_ENABLED` never reached
> the producer so `/train` was unreachable; and **the ServiceAccount security layer CrashLooped every
> Dapr pod**. Plus: input version pins were emitted then dropped on ingest (280 READ edges, 0 versions
> — now persisted). **FOLLOW-UP SESSION (same day): the trainer-lineage-credential gap is now CLOSED
> (a `ServicePrincipal` service door — governed /train lineage lands as `service-trainer`, e2e-guarded),
> and closing it exposed a 7TH live-only bug — the RustFS securityContext uid was wrong (1000 vs the
> image/data's 10001), so the §6.3 flip left the data plane WRITE-DEAD while reads passed (my proof was
> read-only). Remaining open: PSA `restricted` (blocked by the Dapr sidecar), and the run-inputs API.**
> **The recurring shape across all seven: "wired only in the movers loop" / "the flag was never actually
> deployed" / "the proof only tested the easy direction" — config-surface + verification-gap bugs that
> unit tests and chart-render CI structurally cannot see.**

## 1 · Dapr usage (per the dapr skill)

- ✅ **Pub/sub, subscriptions, ack semantics, token guards** — two audits (GOAL-3 Dapr audit + the §2
  bus-correctness cluster, 9 fixes): declarative subscriptions via `DaprApp`, CloudEvent envelopes,
  SUCCESS/RETRY/DROP acks, `dapr-api-token` on every sidecar-delivered route with the fail-closed
  boot assert, publisher scopes, cron binding (OPTIONS pre-flight now route-tested).
  Re-verify: `make e2e` (umbrella) + `uv run pytest tests/unit/test_dapr_auth.py`.
- 🟡 **Resiliency policies** — redelivery is bounded (maxDeliver) and chaos-verified for the mover
  path; there is no standing automated chaos suite (see §5 below).

## 2 · Event-driven, durable, recoverable

- ✅ **Durable consumers on every deliverPolicy=new subscriber** (movers + media head):
  `<app-id>-durable`. Chaos-verified 3-phase (2026-07-06): publish-while-mover-down → message
  retained in JetStream → consumed on restart; redeploy leaves no orphan consumer.
- ✅ **At-least-once + idempotent everywhere**: deterministic uuid5 run-ids per (operation, token),
  AGE MERGE upserts (single sorted property-bearing pass — deadlock-free, live-reproduced then fixed),
  /events dedup incl. the redelivered-terminal-with-fresh-eventTime case (real-Postgres test in CI:
  `dagger call test-lineage`).
- ✅ **Lineage subscriber deliberately ephemeral** (deliverPolicy=all): replay rebuilds the graph;
  documented in the chart comment. Not a gap — a design choice.
- 🟡 **Chaos rows are point-in-time** (docs/RESILIENCE.md honesty note): pull-a-service recovery was
  demonstrated once per row, not encoded as a standing suite. NATS is single-node on kind (SPOF —
  prod needs a 3-replica JetStream cluster; parked with §12).

## 3 · Multimodal (blobs)

- ✅ **Inline-copied blobs** through catalog create (blob v2, 2.2, stable row ids) — live-verified.
- ✅ **External-pointer blobs** (`Blob.from_uri`) through catalog create + the registered-bases
  allowlist — live-verified.
- ✅ **Media lane in the deployed cascade**: `/ingest-media` → blob bronze → content-dispatched
  derivation (thumbnail + embedding) → silver, with source-URI provenance. `make e2e-media`, and as
  of 2026-07-06 **under full governance** (`make e2e-governed-union` test 4).
- ✅ **Blobs through the RAY stage job — CLOSED 2026-07-13 (Phase 3).** The premise was VERIFIED live
  (not assumed): `lance_ray.read_lance` strips blob-v2 typing → plain `large_binary` (schema before/after
  proven), so the Ray job re-wraps via pylance instead. `ray_stage_job.py` now has a media path
  (read_blobs → blob_array → derive thumbnail+embedding → write 2.2), the ray image ships Pillow, the
  deriver is drift-pinned to services/medallion/services/media.py, and the `has_blob_columns` fallback
  gate is GONE. Live: `/ingest-media` (ray on) → media stage ran AS A RAY JOB (no `medallion_ray_blob_fallback`),
  `silver-media` has `payload` still blob-v2 + derived thumbnail+embedding. lance-ray bump = drop the
  round-trip (docs/RAY.md exit note); the deriver is our logic, stays.

## 4 · Ray compute (tabular)

- ✅ **Real Ray cluster driven by the cascade**: `ray job submit` per stage trigger; distributed
  write / scalar+vector index / schema evolution / compaction proven vs RustFS (`make ray-demo`,
  docs/RAY.md — incl. the documented pylance-8↔lance-ray version landmines and native fallbacks).
- 🟡 **Ray Train vs Ray Data distinction — DESIGN DECIDED 2026-07-10** (added 2026-07-06, user;
  task #115): the contract is `docs/RAY-TRAIN.md` — separate `/train` head + own topic,
  submit-and-ack trainer (no auto-resubmit), official jobType=TRAINING facet with per-feature
  version pins, **model registry = Lance dataset `models$<model>` pointing at plain-path S3
  artifact objects** (bytes first, one atomic registry commit second; time-travel = model
  versioning; tags + validator rung = promotion; serving loads the plain path, no Lance reader),
  dedicated `service-trainer` identity (features reader + models writer only), shared Jobs-REST
  seam now → KubeRay RayJob at the rask merge. Implementation #115a–c ALL code-complete
  (2026-07-10/11, unit tier + adversarial reviews): head + consumer + `scripts/ray_train_job.py`
  (pinned-version reads, bytes-then-commit registry publish, self-emitted TRAINING lifecycle
  lineage with a reconcile-recoverable dataSource facet) + trainer grants + the `TRAINING`
  JetStream stream. **✅ LIVE-DRIVEN 2026-07-13** (todo_fable §7a): POST /train → 202 with pinned
  feature versions → Ray job SUCCEEDED → `weights.json` loads from the PLAIN S3 path → registry commits
  as a Lance dataset; redelivery re-attaches with NO duplicate job; FGA deny → no job; FAIL path → a
  FAILed job. Chart values passthrough landed. Three bugs fixed to get there (TRAIN_TOKEN collision,
  producer ray env, the dead FGA gate — §7a). ✅ **TRAINER LINEAGE CREDENTIAL CLOSED 2026-07-13**: the
  job now authenticates to the HTTP ingest as the SERVICE it is (app token + bare FGA subject
  `service-trainer`, a `ServicePrincipal` — NOT a Dex user, per D3), is stamped as author, and is still
  FGA-checked on the outputs. Live-proven: governed /train → COMPLETE attributed to `service-trainer`,
  zero 401s (was: graph empty). Guarded by a new governed-union e2e sub-phase (5 passed / 191s). The
  fix uncovered + fixed a 7TH live-only bug: RustFS `infraContexts.runAsUser` was 1000 but the image +
  on-disk data are uid 10001, so under the §6.3 flip RustFS READ fine but every WRITE 500'd — the whole
  data plane was write-dead (my §6.3 proof was read-only). Corrected to 10001.

## 5 · Auth / authz (can and can't)

- ✅ **OIDC boundaries**: anon → 401, malformed bearer → 401 (`make e2e-governance`).
- ✅ **ReBAC can/can't**: non-owner rename/overwrite → 403, owner keeps access; verified creator in
  lineage; model proven offline (`model.fga.yaml`) + live.
- ✅ **Governed FULL UNION driven live (2026-07-06)**: `make e2e-governed-union` (4 passed / 126s) —
  allow-path cascade under seeded service grants; **FGA-deny→DROP live** (gold validator tuple
  revoked via the OpenFGA API → gold's run never lands; re-grant restores — attributable enforcement);
  ungranted user 403; transitive-disclosure filter hides ungranted datasets incl. s3:// sources.
  🟡 2026-07-10: the suite grew the §7a hardenings (WRITER-gate deny sub-phase + measured
  past-redelivery-window re-asserts, fixture teardown, order independence; the s3://-filter positive
  control was RESOLVED AS IMPOSSIBLE — OpenFGA object ids can't hold an s3 URI, see todo_fable §7a) —
  code-complete + gate-green, but the 4/4 live evidence above predates them: re-run
  `make e2e-governed-union` on the union stack to re-confirm.
- ✅ **Trainer rung (#115 D5) — DEAD UNTIL 2026-07-13, NOW ENFORCED LIVE**: the FGA envs rendered only
  inside the movers `range`, so the TRAINING consumer (hosted by the producer app) ran with
  `fga_client=None` and its gate silently no-op'd — a REVOKED trainer still trained. Fixed + live
  deny-test: revoked grant → 202 token but ZERO Ray jobs; re-grant → job runs to SUCCEEDED.
- ✅ **Governed lineage visibility for humans** — the seed script now writes table→namespace parent
  tuples for mover datasets (before 2026-07-06 the medallion estate was invisible to ALL humans under
  LINEAGE_FGA_ENABLED — found + fixed while building the union e2e).

## 6 · Secrets / OpenBao

- ✅ **Two-tier model**: app services fail-closed on OpenBao as sole source; infra owners use k8s
  Secrets; prod render carries 0 plaintext secrets in env/args/command (verified earlier); RustFS on
  a keep-PVC.
- ⛔ **OpenBao × medallion-compute is an un-integrated combination**: the compute path reads S3 creds
  from env only, so the full union runs `openbao.enabled=false`. Closing it = medallion fetches S3
  creds from OpenBao like catalog/lineage/compaction do, then re-run `make e2e-governed-union` with
  OpenBao ON.

## 7 · Object store (RustFS / S3)

- ✅ **Conditional-write (CAS) validated** — Lance manifest commit safety rests on it; two-layer
  verdict via `make e2e-cas`. Path-style signing everywhere; scheme never silently downgraded.

## 8 · Quality gates

- ✅ **Unit-proven contract** (assertions, passed(), UnderivableMediaError DROP-not-RETRY) **and
  live-proven blocking (2026-07-06)**: nulled-id bronze → silver written, `quality_passed=false` +
  failed `not_null(id)` recorded on the WROTE edge, gold NEVER triggered, `/produce` recovers.

## 9 · Lineage (everywhere, incl. Ray)

- ✅ **Emit coverage audited + closed**: create/register/declare/drop/deregister/schema-evolution/
  index/restore + measured writes; per-version schema facets; failed runs recorded without fabricated
  lineage; spec-true (official client classes; RunEvent shape pinned by tests).
- ✅ **Through the Ray path**: the full-cascade e2e catches ALL events incl. the schema facet when
  stages run as Ray jobs (the mover measures the job's written dataset and emits — Ray=compute,
  Lance=data, by design).
- ✅ **Governed reads** (metadata gate + transitive-disclosure filter + /graph + /columns + /events +
  /runs folds) — unit + governed-union live.
- ✅ **Input version pins persisted (fixed 2026-07-13)** — the graph held **280 READ edges and ZERO
  versions**: the Ray TRAIN job emits spec-true `datasetVersion` facets on its inputs (#115 D1's
  reproducibility claim) and the ingest dropped every one, so the graph could not answer *which feature
  versions produced this model*. `RunEvent.input_version()` + a READ-edge SET now record it (live:
  version 28 on the edge; the pre-fix run's edge is still blank). ⛔ Follow-up: no API surfaces a run's
  INPUTS at all — the pin is reachable only by Cypher (/runs returns outputs; /graph is dataset→dataset).
- 🟡 **`/insert` version attribution** — read-after-write (upstream response carries only a
  transaction_id); reconcile heals drift. Blocked upstream; documented.
- 🟡 **Compaction FAILURES invisible to lineage/APIs — CODE-COMPLETE (2026-07-10)**: FAIL RunEvent per
  maintain:-errored dataset (deterministic run_id flood guard, errorMessage facet, capped concurrent
  fan-out, `defer_index_remap=True` + real-Lance interplay regression) — 10 unit tests green. Pending:
  ✅ **LIVE-PROVEN 2026-07-13**: fault-injected a dataset (deleted one data file under its manifest) →
  exactly ONE FAIL Run node with the deterministic id `2e0e2470-…` (= uuid5 of
  `compaction-fail-faultns$sacrifice`), errorMessage facet carrying the Lance IO error, no flood across
  ticks, and the sweep kept processing every other dataset.

## 10 · Compaction / GC

- ✅ **Sweep works**: real compact+GC per dataset, measured reclaim, `make e2e-compaction`; Ray
  distributed compaction in `make ray-demo`.
- 🟡 **Failure visibility** — see §9 last row (same item; code-complete 2026-07-10, live proof pending).

## 11 · Observability

- ✅ **OTLP-direct pipeline** (GreptimeDB + Vector + Perses), distributed traces across Dapr,
  `make e2e-obs` regression guard.
- 🟡 **Lance-native IO metrics PRE-WIRED (2026-07-10)** — all five Lance-I/O lifespans call the guarded
  `common.lance_metrics.instrument_lance_if_available()`; a no-op at pylance 8.0.0 (the NEWEST PyPI
  release — verified; `lance.otel` is a 9.0 feature). Activation = switch the pin to `pylance[otel]`
  at the 9.0 bump (pyproject marks the spot), then re-run `make e2e-cas` (data-plane major bump
  re-opens the commit-safety verdict) + the real-Lance tripwire tests. 3 unit tests pin the guard.
- ✅ **App logs ship to GreptimeDB via OTLP, NOT stdout** (confirmed 2026-07-13): auto-instrumentation
  (`OTEL_LOGS_EXPORTER=otlp`) attaches a root handler, so `kubectl logs` carries only uvicorn access
  lines. Query `opentelemetry_logs` instead — `dapr_dead_letter_parked`, `train_denied`,
  `train_trigger_malformed` all present there. Every "the app logs X" assert is a Greptime query.
- 🟡 **Greptime/Perses are unauthenticated in-cluster** — acceptable on kind; prod hardening parked
  with §12.

## 12 · Production-only residuals (PARKED — one-line notes, per the active goal)

- ⛔ L3 default-deny NetworkPolicies + OpenBao isolation: never applied on kind — kind's default CNI
  (kindnet) silently IGNORES NetworkPolicy, so it is unprovable here (needs Calico/Cilium).
- ✅ **Per-workload ServiceAccounts + infra securityContexts — FLIPPED AND PROVEN LIVE 2026-07-13**
  (both were 🟡 chart-only): SAs bound, k8s token NOT mounted, daprd clean, cascade flows; infra runs
  non-root (age 999, openbao 100, rustfs **10001**) and a restart kept 441 AGE Run nodes + 392 RustFS
  objects. The SA flip was UNSHIPPABLE before the pass — it CrashLooped every Dapr pod (§7a bug 6).
  🔴 **CORRECTION (bug 7): the rustfs securityContext was WRONG (uid 1000) and my first fsGroup "proof"
  was READ-ONLY, so it false-passed.** The rustfs image + its on-disk data are uid **10001**; under a
  1000 context RustFS reads fine but every WRITE 500s (`Io error: Permission denied`) — the whole data
  plane was write-dead, caught only when a governed train job failed to write weights.json. Fixed to
  10001/10001. Lesson pinned: an fsGroup/securityContext proof MUST include a write, not just a list.
- ⛔ **PSA `restricted` is UNREACHABLE** (disproven live 2026-07-13; the runbook's old "nothing should
  be rejected" was wrong): it BLOCKS pod creation on the Dapr-injected `daprd` sidecar (needs
  `capabilities.drop=[ALL]` + `seccompProfile`), and `baseline` would make Vector un-reschedulable
  (hostPath). Namespace left at `warn`+`audit`=baseline. See KIND-RUNBOOK §6.4 for what it needs.
- ⛔ NATS JetStream HA (3 replicas) — single-node on kind.
- ⛔ Query/consumption engine — deliberately NOT built yet (user decision 2026-07-06: consumption is
  a future query engine; do not build /search now).
- ⛔ Frontend suites in CI (Playwright + bun) — parked with the no-frontend-work scope.
- ⛔ Backup automation is gated/opt-in (VolumeSnapshot + pg_dump CronJobs exist; restore drill is the
  §12 item).
