# todo_confirm — the "don't miss a thing" verification matrix

One row per pillar-claim: what is **CONFIRMED live** (with the exact evidence + the command that
re-proves it), what is confirmed **WITH A CAVEAT**, and what is still **OPEN**. This is the checklist
for "is the lakehouse actually working as intended", kept honest per the §0 rule: *"tested" means
driven in the shipped combination, not unit-passed.* Update a row only with transcript evidence.

Legend: ✅ confirmed live · 🟡 confirmed with a named caveat · ⛔ open (not yet true / not yet proven)

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
- ⛔ **Blobs through the RAY stage job** — lance-ray reads blob bytes fine (take_blobs) but strips
  the blob typing on read, so the job's write-back would demote the column; the ray image lacks the
  deriver. Movers currently take an OBSERVABLE in-process fallback (`medallion_ray_blob_fallback`).
  = Phase 3 of the active goal: blob_field re-attach on write-back + deriver in the ray image, drop
  the gate, prove media-on-Ray live.

## 4 · Ray compute (tabular)

- ✅ **Real Ray cluster driven by the cascade**: `ray job submit` per stage trigger; distributed
  write / scalar+vector index / schema evolution / compaction proven vs RustFS (`make ray-demo`,
  docs/RAY.md — incl. the documented pylance-8↔lance-ray version landmines and native fallbacks).
- ⛔ **Ray Train vs Ray Data distinction** (added 2026-07-06, user): the platform must host BOTH
  batch/ETL (today's cascade) and TRAINING workloads. Open design: separate head endpoint
  (`/train`?) vs a workload-type field on the trigger; a training run's lineage shape (OpenLineage
  `jobType` job facet — processingType/integration/jobType — inputs = versioned feature datasets,
  output = model artifact… stored where: Lance dataset? registry?); whether training gets its own
  FGA service identity + rung. Needs a design note + execution spec before code. (Task #115.)

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
- 🟡 **`/insert` version attribution** — read-after-write (upstream response carries only a
  transaction_id); reconcile heals drift. Blocked upstream; documented.
- 🟡 **Compaction FAILURES invisible to lineage/APIs — CODE-COMPLETE (2026-07-10)**: FAIL RunEvent per
  maintain:-errored dataset (deterministic run_id flood guard, errorMessage facet, capped concurrent
  fan-out, `defer_index_remap=True` + real-Lance interplay regression) — 10 unit tests green. Pending:
  the live fault-injection proof on kind (ONE FAIL node across ≥2 cron ticks, lineageEmit=true) +
  compaction image roll. Re-verify: `uv run pytest tests/unit/test_compaction_lineage.py
  tests/unit/test_compaction_optimize.py` + the §7a RESIDUAL live check.

## 10 · Compaction / GC

- ✅ **Sweep works**: real compact+GC per dataset, measured reclaim, `make e2e-compaction`; Ray
  distributed compaction in `make ray-demo`.
- 🟡 **Failure visibility** — see §9 last row (same item; code-complete 2026-07-10, live proof pending).

## 11 · Observability

- ✅ **OTLP-direct pipeline** (GreptimeDB + Vector + Perses), distributed traces across Dapr,
  `make e2e-obs` regression guard.
- 🟡 **Greptime/Perses are unauthenticated in-cluster** — acceptable on kind; prod hardening parked
  with §12.

## 12 · Production-only residuals (PARKED — one-line notes, per the active goal)

- ⛔ L3 default-deny NetworkPolicies + OpenBao isolation: prod-values only, never applied on kind.
- ⛔ NATS JetStream HA (3 replicas) — single-node on kind.
- ⛔ Query/consumption engine — deliberately NOT built yet (user decision 2026-07-06: consumption is
  a future query engine; do not build /search now).
- ⛔ Frontend suites in CI (Playwright + bun) — parked with the no-frontend-work scope.
- ⛔ Backup automation is gated/opt-in (VolumeSnapshot + pg_dump CronJobs exist; restore drill is the
  §12 item).
