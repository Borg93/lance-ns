# GOAL — Production readiness (round 1)

Living tracker for hardening the Lance-lakehouse estate from "feature-complete + verified on kind" to
"operable in production". Grounded in an adversarially-verified audit (2026-07-17, 12-agent workflow):
40 gaps confirmed real, 3 rejected as already-handled. Each item below was confirmed by re-opening the
cited file, so this is real work, not a generic checklist.

**Post-phase re-audit (2026-07-17, 33-agent adversarial sweep over the whole phase diff, 6 lenses + 3-refuter
verification):** 5 confirmed never-driven-union defects, all fixed — DaprConsumerWedge keyed on a metric that
doesn't discriminate a wedge (→ `dapr_component_pubsub_ingress_count{process_status="retry"}`, the live-
verified signal); the pg-backup CronJob and openfga-migrate hook pods carried no component label so the prod
NetworkPolicy default-deny silently blocked backups + the install hook (→ labels added, `backup-pg` allowed
to rustfs); the load-shed `/create` suffix over-matched cheap metadata creates (→ gate on the Arrow-IPC
content-type); the chaos drill's OpenFGA leg didn't exercise the authz check on a root create (→ probe a
child create under an owned parent). All CI-green.

## Scope & exclusions

**In scope:** resilience/availability, prod security posture, durability/backup/DR, observability/SLOs,
capacity/fault-injection, upgrade/migration safety — as they apply to what the chart + services ALREADY
ship.

**Hard exclusions (parked / off-limits — do not touch here):**
- NATS HA / JetStream clustering / the query-consumption engine (goal #20, user-parked).
- The rask-merge / KubeRay `RayCluster` CR migration (Ray runs as a single-head demo deploy on purpose).
- Speculative future-backend features (verify a capability ships before building on it).

**The two big structural SPOFs — RustFS and AGE-Postgres single-replica — are NOT solved in-chart here**
(that needs an object-store operator / CloudNativePG, i.e. the same class as the parked items). The chart
already wires `rustfs.externalEndpoint` / `age.externalHost`; the prod answer is *externalize to a managed
store*, captured as a runbook item (P7), not an in-chart HA rewrite.

## Verification rhythm (per increment)

Code changes: unit test + live kind redeploy (digest-verify + pod-delete) + drive the real flow. Chart
changes to the prod overlay (can't run on the kind demo): `helm template -f values-prod.yaml` render
assertions + confirm the default (kind) render still deploys. Every increment: all 6 CI jobs green, pushed
to main. Never weaken auth/secrets posture.

---

## P1 — Fail-closed correctness + the headline security flip (S-effort, high value, low risk)

- [x] **`/readyz` asserts graph health** (HIGH·code) — DONE (aed8014): `/readyz` now runs
  `run_cypher(graph,'RETURN 1')` after `SELECT 1`. Proven live — lineage became Ready in all three e2e jobs
  (the readiness probe runs the graph check).
- [x] **Medallion cascade DLQ metric** (HIGH·code) — DONE (aed8014): `record_dead_letter(app)` increments
  `medallion.dlq.parked` on a parked delivery; unit-tested via a metric spy.
- [x] **startupProbe on the FastAPI apps** (MED·chart) — DONE (aed8014): 300s startup budget on
  `lance.appProbes`; default render clean, all e2e rollouts healthy.
- [x] **Enable NetworkPolicy in `values-prod.yaml`** (HIGH·chart) — DONE (P1b): `networkPolicy.enabled=true`
  in the prod overlay. Render-verified (10 policies incl. default-deny + openbao lock). Live negative-
  isolation probe stays a prod acceptance step (needs a Calico/Cilium cluster; kind's CNI ignores policies).
- [x] **OpenFGA HA in prod** (HIGH·chart) — DONE-partial (P1b): `replicaCount: 3` + resources in
  values-prod (render-verified). Its **PDB + anti-affinity → P2** (need the subchart's own label selector).
- [x] **Dapr control-plane HA in prod** (MED·chart) — DONE (P1b): `dapr.global.ha.enabled=true`; render
  shows operator/sentry/placement/scheduler at 3 replicas + PDBs (vs 1 on default).
- [x] **CI prod-overlay render guard** (NEW·ci) — DONE (P1b): `make prod-render-check` /
  `scripts/prod_render_check.sh`, wired into the `test` job — asserts NetworkPolicy + OpenFGA-3 + Dapr-HA +
  app-PDBs render. Nothing rendered the prod overlay in CI before, so a switch silently reverting to the dev
  posture would have passed green.
- [ ] **GreptimeDB probes + limits** (MED·chart) — 0 probes, unbounded resources; unready store still
  gets OTLP/Perses traffic. Add `/health` readiness/liveness + CPU/mem limits. → folded into **P2**.
- [x] **Catalog memory sizing** (MED·chart) — DONE: prod now ships an explicit, coherent load-shed cap.
  The chart wires `catalog.maxConcurrentWrites` into `LANCE_MAX_CONCURRENT_WRITES` (hasKey+ternary, reuse-
  values-safe); values-prod sets 2 with the sizing formula (2 × 256MiB buffered bodies + 512Mi headroom =
  the 1Gi tier). prod-render-check check 9 asserts the arithmetic (cap × maxBodyBytes + 512Mi ≤ limit), so
  the coherence can't silently regress — proven to trip on cap=4/16. Kind/default stays the code default 16.

## P2 — Resilience topology (M-effort chart)

- [x] **External-Postgres AGE bootstrap** (HIGH) — DONE (P2a, 0480c21): lineage `ensure_graph()` on boot
  creates the graph if absent (self-healing + the only bootstrap on the managed-PG path), fatal on a real
  failure. Real-AGE e2e proves create + idempotency; e2e-stack proves the boot path live.
- [x] **Pod anti-affinity / topologySpreadConstraints** (HIGH) — DONE (P2b): soft hostname spread
  (`lance.spreadConstraints`, ScheduleAnyway) on catalog/lineage/gateway/web, gated on
  `podDisruptionBudget.enabled` (prod). Render-verified (spread=4); off on the default kind render.
- [x] **OpenFGA PDB** (HIGH, was P1 carry-over) — DONE (P2b): a PDB on the subchart's `name: openfga`
  selector in ha.yaml. Completes the P1b OpenFGA-HA item (3 replicas + PDB). prod-render-check asserts it.
- [x] **Per-workload resource tiers** (HIGH) — DONE (P2c): a `lance.resources` helper (resources.<comp>
  else resources.default) wired into catalog/age/rustfs; prod tiers them to 1Gi (catalog Arrow buffer, age
  dual graph+FGA store, rustfs data plane). Render-verified (prod tiers=3, default=0). Folds in the P1
  catalog-memory item. Remaining workloads (movers/lineage) keep the default until load data says otherwise;
  wiring them through the helper is a trivial follow-up.
- [ ] **GreptimeDB probes** (MED) — BLOCKED by the vendored subchart: greptimedb-standalone-0.4.5's
  statefulset templates NO probe hooks (only `resources` is settable). Needs a newer greptime chart or a
  post-render patch — defer. Its RESOURCE LIMITS fold into the resource-tiers item above.
- [ ] **Telemetry-store SPOF sharing data-plane disk** (HIGH) — separate GreptimeDB's storage from the
  data-plane volume; monitor it.

## P3 — Observability & operability (critical/high)

- [x] **Alert rules, proven to fire** (CRIT — P3b-1 DONE): `chart/alerting/rules.yml` — 5 rules seeded from
  the "alertable" panels (outbox not-draining / backlog-aging, lineage + medallion dead-lettering, stage
  FGA-denied), on metrics the estate actually emits. `chart/alerting/rules_test.yml` PROVES they fire on
  synthetic series (`promtool test rules`, hermetic — the proof render-checking can't give); `make
  alert-rules-check` runs check+test, wired into the CI test job.
- [x] **Deploy the evaluator** (CRIT — P3b-2 DONE): `chart/templates/alerting.yaml` — vmalert (mounts the
  proven rules via `.Files.Get`, queries GreptimeDB's `:4000/v1/prometheus`, notifies Alertmanager) +
  Alertmanager (groups + routes; `webhookUrl` → Slack/PagerDuty), gated on `observability.alerting.enabled`
  (on in prod). Render-verified (default off; prod deploys both + mounts the real rules); prod-render-check
  asserts it. REMAINING drill (needs a live cluster): the vmalert→GreptimeDB query round-trip + wiring a real
  Alertmanager receiver. The alert LOGIC is already proven (P3b-1 promtool), so only the transport is unproven.
- [x] **Symptom-indexed on-call runbook** (HIGH·runbook) — DONE (P3a): `docs/RUNBOOK-oncall.md` — a symptom
  index + per-mode symptom→cause→diagnose→act for OpenFGA-down (503-everywhere), OpenBao sealed (boot
  deadlock), CrashLoop-on-boot, /readyz degraded (pool vs graph), cascade stalled, DLQ parking, outbox not
  draining, RustFS down, AGE down. Grounded in the real services/metrics/fail-closed behaviors.
- [~] **Infra-tier metrics collection** (CRIT·chart) — the Dapr sidecars expose `:9090` Prometheus metrics
  nothing pulled, so a consumer-wedge (a subscriber retrying forever, cascade silently stalled) is invisible.
  The **alert LOGIC is DONE**: the `DaprConsumerWedge` rule keys on
  `dapr_component_pubsub_ingress_count{process_status="retry"}` (the live-verified per-delivery retry outcome)
  sustained 15m, promtool-proven to fire and to stay silent on a busy-healthy consumer. The COLLECTION is
  deliberately deferred to the **OTel Collector** (operator adoption): a first pass shipped a `vmagent`, but
  that was a redundant third collector (the estate already runs Vector for infra logs + OTLP-direct for apps),
  so it was **removed** — the Collector's `prometheus` receiver (k8s SD) owns the Dapr scrape and subsumes
  Vector too. The rule evaluates the moment the Collector feeds `dapr_*` into GreptimeDB. See docs/OPERATORS.md #7.
- [x] **Trace continuity across Ray + Dapr boundary** (MED·code) — DONE at the unit tier: both in-service
  submission sites (`ray_submit.submit_stage_job`/`submit_train_job`) inject the active span's W3C
  traceparent into the job `runtime_env` (`opentelemetry.propagate.inject` — nothing injected without a
  real active span, never fabricated); both job scripts run their whole work under one root span parented
  on the extracted context (inline build→flush→shutdown, guarded imports for the separate Ray image),
  degrading to untraced on missing/garbage TRACEPARENT or missing SDK. Failures — including the jobs' own
  `SystemExit` verification exits (BaseException, which the SDK alone would leave green) — mark the span
  ERROR. 13 unit tests incl. a drift-pin holding the two inlined helper copies byte-identical. REMAINING
  (drill): one live cascade with tracing on to see the joined catalog→…→ray span in GreptimeDB.

## P4 — Backup / restore / DR (critical/high)

- [x] **Restore procedure + AGE-restore drill** (HIGH — P4a + P4b): `docs/RUNBOOK-restore.md` authors the
  order-sensitive AGE-aware restore; **P4b now PROVES it** — `scripts/age_restore_drill.sh` runs inside the
  age-postgres pod (throwaway DB, never touches the real graph) doing the RUNBOOK's exact pg_dump→drop→restore
  and VERIFYING the graph came back with its labels + vertex (not just ag_catalog metadata — the known
  plain-pg_dump-of-AGE hazard). Wired into `e2e_stack.sh` (gated `E2E_RESTORE_DRILL`). **PROVEN GREEN**
  (e23b077): the drill passes (restored-Dataset-vertex-count=1), so a plain pg_dump DOES round-trip the AGE
  graph for the pinned engine — the hazard did not materialise; the restore is authored AND proven. (An
  AGE-aware dump would still be more robust across a Postgres-major restore — see P6.)
- [ ] **AGE-graph backup that doesn't share fate with the primary** (CRIT) — the pg_dump lands on RustFS, so
  a total RustFS loss loses BOTH the Lance data and the DB dumps (documented in RUNBOOK-restore.md). Ship the
  dumps off-cluster (a second object store / off-site), or externalize to CNPG PITR (P7).
- [~] **Backup retention/pruning** (MED) — DONE (P4c): the pg-backup CronJob now prunes all but the newest
  `backups.pgDump.keep` dumps each run (default 7; 0 disables) so the `_backups/pg/` prefix doesn't grow
  unbounded. Render-verified. REMAINING in this item: a documented RPO/RTO + verifying the VolumeSnapshot
  actually succeeds (the empty snapshotClassName is a per-cluster value).
- [ ] **OpenBao PVC backup** (MED) — the file-backend PVC has no backup path.

## P5 — Fault-injection & load (high/medium)

- [x] **CI dependency-outage chaos drill** (HIGH·ci — P5 #54): a repeatable chaos leg in `e2e_stack.sh`
  (final guarded step, restores + verifies recovery). Covers BOTH gaps below. `E2E_CHAOS=0` escape hatch.
- [x] **RustFS / S3 outage test** (HIGH·test — P5 #54): the chaos leg scales `rustfs` to 0 and asserts a
  governed namespace CREATE (a genuine S3 write) fails **closed** (5xx, never a silent 200 = data loss), then
  recovers. The data-plane outage was entirely untested before.
- [x] **OpenFGA-down live outage test** (MED·test — P5 #54): the chaos leg scales `openfga` to 0 and asserts
  a governed create fails **closed** (5xx, never fail-open 200), then recovers — the live counterpart to the
  mock-only unit test.
- [x] **App-level load-shedding** (MED·code) — DONE (P5, #54): `WriteConcurrencyLimitMiddleware` caps
  concurrent Arrow-IPC writes (create/insert/merge_insert) and sheds the overflow with **429** (the
  `THROTTLING` mapping that had no producer) + `Retry-After`, BEFORE the body is buffered — so shedding
  relieves the N×256MiB OOM the P2c memory tier only partly bounds. Pure-ASGI, sits above body_limit;
  `LANCE_MAX_CONCURRENT_WRITES` (default 16, 0=off); a `catalog.writes.shed` metric. Unit-tested at the ASGI
  layer (over-cap → 429 before the app; reads + /commit ungated; 0 disables).
- [x] **Compaction sweep single-flight** (MED·code) — DONE (P5a): an in-process `asyncio.Lock` with
  skip-on-overlap on `on_cron` (compaction is stateless — no DB for a pg advisory lock like reconcile; with
  compactionReplicas=1 this is cluster-wide). A slow sweep now self-limits by skipping ticks instead of
  starting a 2nd concurrent sweep that races compact/GC on the same datasets. Unit-tested. The explicit
  per-tick DATASET bound (needs a rotation cursor to avoid tail-starvation) is a deferred follow-up.
- [ ] **Reconcile sweep per-dataset bound** (MED·code) — DEFERRED: the reconcile sweep already single-flights
  (pg advisory lock) + caps the outbox drain, but `reconcile_all` still scans EVERY dataset per tick. A bound
  needs a PERSISTED name-cursor (resume-after-last, shared across the 2 replicas the advisory lock hands the
  tick to) to avoid tail-starvation — a bigger, careful change than the stateless compaction guard. Park
  until estate size demands it.

## P6 — Upgrade & migration safety (medium)

- [x] **AGE Postgres-major image-bump migration** (MED·runbook) — DONE: RUNBOOK-restore.md gained "Planned
  migration — bumping AGE across a Postgres major": the CrashLoop failure signature, why (PVC keeps the
  PG16 datadir; the AGE extension build is also per-major; no in-pod pg_upgrade), the logical-migration
  procedure reusing the pg-backup CronJob dumps + snapshot + restore + a re-drill on the new major before
  cutover, the rollback, and the shared-OpenFGA-database warning. Authored, not yet rehearsed (says so).
- [x] **AGE volumeClaimTemplate immutability** (MED·chart) — DONE: an upgrade-time `lookup` guard on the
  AGE StatefulSet fails the render with the exact resize commands (patch PVC → delete STS --cascade=orphan
  → re-upgrade; runbook section added) when `age.storage` differs from the deployed template. Inert on
  `helm template`/CI (lookup returns empty) — proven live both directions via server-side dry-run against
  the kind release. Known limit: textual compare, so write the same unit the chart installed.
- [x] **`ensure_events_table` DDL statement-timeout safety** (LOW·code) — DONE: the first-boot DDL runs in
  one transaction opened with `SET LOCAL statement_timeout` at the same configured value the pool options
  use (no new knob); the bound is carried by the transaction itself, leaks nothing to pooled sessions, and
  a timeout still fails boot closed. DuplicateTable create-race swallow preserved. Unit-proven.

## P7 — Structural SPOFs → externalize (runbook, not in-chart HA)

- [~] **RustFS single-replica Recreate/RWO SPOF** (HIGH) — the SPOF remains in-chart (no object-store HA),
  but the prod answer — externalize to managed S3 / rustfs-operator — is now documented AND CI-verified: the
  `rustfs.externalEndpoint` handoff is atomic with the GreptimeDB object-store endpoint (`prod-render-check`
  leg 10 fails if either is set without the other — an operator-handoff audit fix). Adopting the operator = flip.
- [~] **AGE-Postgres single-replica SPOF** (HIGH) — SPOF remains in-chart, but the CloudNativePG prod answer
  is now **documented AND proven** (docs/CNPG-AGE.md): AGE reached PG18 (v1.7.0), so it mounts as a CNPG
  **ImageVolume extension** on a stock Postgres image — the extension image (`.docker/cnpg-age-ext.dockerfile`)
  + `Cluster`/`Database` CRs (`deploy/cnpg-age-cluster.yaml`) are built, and AGE was verified end-to-end on
  PG18 locally (`CREATE EXTENSION`/`create_graph`/cypher via `extension_control_path`). Needs K8s 1.33+ (kind
  is 1.31, so the CSI mount is the one untested leg); a custom-full-image PG16 bridge is documented for older
  clusters. CNPG physical PITR supersedes the pg_dump path (safer for AGE). Adopting = flip `age.externalHost`.
- [ ] **Movers cross-pod lock → scale the event-driven tier** (MED·code) — the single-flight lock is
  process-local, capping each stage at 1 mover; a distributed lock to allow >1 is a larger change — park
  with rationale until throughput demands it.
- [ ] **Dex single-replica in-memory SPOF** (LOW) — note the login/token SPOF; externalize the IdP for prod.

## Rejected by the verify pass (already handled — do NOT re-add)

3 candidate gaps were dropped because re-reading the file showed the concern is already covered. (See the
audit journal `subagents/workflows/wf_ed8babda-554/journal.jsonl` for specifics.)
