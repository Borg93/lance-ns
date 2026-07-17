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

- [ ] **`/readyz` asserts graph health** (HIGH·code) — lineage `/readyz` only does `SELECT 1`
  (main.py:139-146); `ensure_graph_constraints` is best-effort non-fatal, so a pod with an absent/broken
  graph reports Ready and silently discards events. Add a `cypher('lineage','RETURN 1')` liveness of the
  graph so a bootstrap/restore failure fails the pod loudly. *Done: unit + a live "break the graph → pod
  goes NotReady" check.*
- [ ] **Medallion cascade DLQ metric** (HIGH·code) — `dapr_dead_letter_parked` (medallion/api/dlq.py:34)
  only logs; lineage's DLQ records `Outcome.DEAD_LETTERED`. Add a bounded-cardinality `dlq_parked` counter
  (labelled app/stage) so a permanently-stalled cascade item is dashboardable + alertable. *Done: unit +
  metric visible in GreptimeDB after a forced park.*
- [ ] **Enable NetworkPolicy in `values-prod.yaml`** (HIGH·chart) — the chart ships a complete default-deny
  + exclusive-openbao-ingress impl (network-policy.yaml) but `values-prod.yaml` never sets
  `networkPolicy.enabled=true`, so the headline isolation stays OFF on the documented prod overlay. Flip it
  + document the Calico/Cilium CNI requirement (kind's CNI ignores NetworkPolicy). *Done: `helm template -f
  values-prod.yaml` renders the policies; note the negative-isolation probe as a prod acceptance step.*
- [ ] **OpenFGA HA in prod** (HIGH·chart) — single replica, no limits, PDB-less (values.yaml:228,
  ha.yaml excludes it), yet every governed call fans in here fail-closed. values-prod: `replicaCount: 3` +
  resources + a PDB (extend ha.yaml). *Done: prod render shows 3 replicas + PDB + limits.*
- [ ] **startupProbe on the FastAPI apps** (MED·chart) — no startupProbe anywhere; liveness arms ~70s after
  boot while lineage's boot can take ~80s (Dapr secret fetch + AGE pool + DDL), so a slow dep blip
  CrashLoops a still-booting pod. Add a generous startupProbe to `lance.appProbes`. *Done: render + kind
  redeploy still healthy.*
- [ ] **GreptimeDB probes + limits** (MED·chart) — 0 probes, unbounded resources; unready store still
  gets OTLP/Perses traffic. Add `/health` readiness/liveness + CPU/mem limits.
- [ ] **Dapr control-plane HA in prod** (MED·chart) — `dapr.global.ha.enabled:false` and values-prod never
  flips it, leaving Sentry (mTLS CA, in the sidecar-cert path) single-replica. Set it true in values-prod.
- [ ] **Catalog memory sizing** (MED·chart) — 512Mi default limit vs its own 256MiB in-memory Arrow-IPC
  body buffer. Give catalog a dedicated higher limit (or lower the body cap).

## P2 — Resilience topology (M-effort chart)

- [ ] **Pod anti-affinity / topologySpreadConstraints** (HIGH) — prod's replicas:2 services can co-locate,
  so one node loss removes the whole service despite the PDB. Add a soft hostname spread to the multi-replica
  Deployments.
- [ ] **Per-workload resource tiers** (HIGH) — every workload shares `resources.default` (1 CPU/512Mi);
  stateful stores + compute movers are sized like stateless request pods. Introduce sized tiers.
- [ ] **External-Postgres AGE bootstrap** (HIGH) — the `age.externalHost` path never creates the graph
  (no `ensure_graph`), so on managed PG the graph is absent + un-self-healing. Bootstrap on connect.
- [ ] **Telemetry-store SPOF sharing data-plane disk** (HIGH) — separate GreptimeDB's storage from the
  data-plane volume; monitor it.

## P3 — Observability & operability (critical/high)

- [ ] **SLOs + alerting rules** (CRIT·chart) — dashboards exist but zero alert rules; the stack can be
  watched, never pages. Define SLOs (ingest latency, cascade lag, error rate, DLQ depth) + Perses/Greptime
  alert rules.
- [ ] **Infra-tier metrics collection** (CRIT·chart) — Dapr/NATS/infra metrics aren't scraped, so a
  consumer-wedge is a silent outage. Wire the infra metrics into GreptimeDB.
- [ ] **Symptom-indexed on-call runbook** (HIGH·runbook) — no "symptom → cause → action" runbook for the
  known failure modes. Author `docs/RUNBOOK-oncall.md`.
- [ ] **Trace continuity across Ray + Dapr boundary** (MED·code) — the distributed trace goes dark at the
  Ray compute boundary; propagate context into the stage/train jobs.

## P4 — Backup / restore / DR (critical/high)

- [ ] **AGE-graph backup that doesn't share fate with the primary** (CRIT) — the backup lives on the same
  volume it's meant to protect. Ship backups off-volume.
- [ ] **Restore procedure + AGE-restorable dump** (HIGH·runbook) — no restore procedure; the pg_dump is
  likely not AGE-restorable as written (needs the AGE load/allow-list + label recreation). Author + PROVE a
  restore.
- [ ] **RPO/RTO + retention/pruning + verified VolumeSnapshots** (MED) — backups off by default, no
  RPO/RTO, unbounded dumps, empty snapshotClassName never verified.
- [ ] **OpenBao PVC backup** (MED) — the file-backend PVC has no backup path.

## P5 — Fault-injection & load (high/medium)

- [ ] **CI dependency-outage chaos drill** (HIGH·ci) — the pull-a-service recovery drills are manual + now
  stale. Add a repeatable chaos leg to CI.
- [ ] **RustFS / S3 outage test** (HIGH·test) — the data-plane outage is entirely untested. Prove
  fail-closed + retry when the object store is down.
- [ ] **OpenFGA-down live outage test** (MED·test) — fail-closed is only mock-proven; drive it against a
  real OpenFGA outage.
- [ ] **App-level rate-limiting / load-shedding** (MED·code) — the `THROTTLING→429` mapping has no
  producer; add ingest backpressure.
- [ ] **Bound the compaction + reconcile sweeps** (MED·code) — per-tick work is unbounded + the compaction
  sweep lacks the single-flight lock the reconcile sweep has.

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
