# GOAL — Production readiness (round 1)

Living tracker for hardening the Lance-lakehouse estate from "feature-complete + verified on kind" to
"operable in production". Grounded in an adversarially-verified audit (2026-07-17, 12-agent workflow):
40 gaps confirmed real, 3 rejected as already-handled. Each item below was confirmed by re-opening the
cited file, so this is real work, not a generic checklist.

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
- [ ] **Catalog memory sizing** (MED·chart) — 512Mi default limit vs its own 256MiB in-memory Arrow-IPC
  body buffer. Give catalog a dedicated higher limit (or lower the body cap). → folded into **P2** (per-
  workload resource tiers).

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
- [ ] **Infra-tier metrics collection** (CRIT·chart) — Dapr/NATS/infra metrics aren't scraped, so a
  consumer-wedge is a silent outage. Wire the infra metrics into GreptimeDB.
- [ ] **Trace continuity across Ray + Dapr boundary** (MED·code) — the distributed trace goes dark at the
  Ray compute boundary; propagate context into the stage/train jobs.

## P4 — Backup / restore / DR (critical/high)

- [x] **Restore procedure + AGE-restore drill** (HIGH — P4a + P4b): `docs/RUNBOOK-restore.md` authors the
  order-sensitive AGE-aware restore; **P4b now PROVES it** — `scripts/age_restore_drill.sh` runs inside the
  age-postgres pod (throwaway DB, never touches the real graph) doing the RUNBOOK's exact pg_dump→drop→restore
  and VERIFYING the graph came back with its labels + vertex (not just ag_catalog metadata — the known
  plain-pg_dump-of-AGE hazard). Wired into `e2e_stack.sh` (gated `E2E_RESTORE_DRILL`). A red = a real finding:
  switch backup-pg.yaml to an AGE-aware dump. Turns the restore from *authored* to *proven*.
- [ ] **AGE-graph backup that doesn't share fate with the primary** (CRIT) — the pg_dump lands on RustFS, so
  a total RustFS loss loses BOTH the Lance data and the DB dumps (documented in RUNBOOK-restore.md). Ship the
  dumps off-cluster (a second object store / off-site), or externalize to CNPG PITR (P7).
- [ ] **RPO/RTO + retention/pruning + verified VolumeSnapshots** (MED) — backups off by default, no
  RPO/RTO, unbounded dumps, empty snapshotClassName never verified.
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

- [ ] **AGE Postgres-major image-bump migration** (MED·runbook) — AGE is PG16-pinned; a routine image bump
  is an unhandled data migration. Document + guard.
- [ ] **AGE volumeClaimTemplate immutability** (MED·chart) — changing `age.storage` makes `helm upgrade`
  fail hard; document/guard the immutable field.
- [ ] **`ensure_events_table` DDL statement-timeout safety** (LOW·code) — first-boot dedup DELETE + CREATE
  UNIQUE INDEX isn't statement-timeout-safe on a large table.

## P7 — Structural SPOFs → externalize (runbook, not in-chart HA)

- [ ] **RustFS single-replica Recreate/RWO SPOF** (HIGH) — document + verify the `rustfs.externalEndpoint`
  managed-S3 path as the prod answer (no in-chart object-store HA).
- [ ] **AGE-Postgres single-replica SPOF** (HIGH) — document + verify the `age.externalHost` managed-PG
  path (CloudNativePG / RDS) as the prod answer.
- [ ] **Movers cross-pod lock → scale the event-driven tier** (MED·code) — the single-flight lock is
  process-local, capping each stage at 1 mover; a distributed lock to allow >1 is a larger change — park
  with rationale until throughput demands it.
- [ ] **Dex single-replica in-memory SPOF** (LOW) — note the login/token SPOF; externalize the IdP for prod.

## Rejected by the verify pass (already handled — do NOT re-add)

3 candidate gaps were dropped because re-reading the file showed the concern is already covered. (See the
audit journal `subagents/workflows/wf_ed8babda-554/journal.jsonl` for specifics.)
