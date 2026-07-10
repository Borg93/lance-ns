# Ray TRAIN vs Ray DATA — the training-workload design (task #115)

**Status: DESIGN DECIDED 2026-07-10 (this note is the contract; implementation items are
execution-spec'd in `todo_fable.md` §9 as #115a–c).** The platform must host BOTH batch/ETL
(today's medallion cascade — the Ray *Data* shape) and TRAINING workloads (Ray *Train*). They are
different workload classes and get different runtime treatment — but ONE provenance model, ONE
authz model, and ONE storage substrate.

| | Ray DATA (today's cascade) | Ray TRAIN (this design) |
|---|---|---|
| Duration | bounded stage transform (seconds–minutes) | long-running (minutes–hours), often GPU |
| Trigger semantics | stage hop: mover blocks until the job lands, then fires the next stage | fire-and-track: submit + ack; the JOB reports its own lifecycle |
| Output | the next stage's Lance dataset (+ version) | a MODEL artifact |
| OpenLineage `jobType` | `ETL` / `TRANSFORMATION` | `TRAINING` |
| Failure policy | RETRY (redelivery re-runs the transform) | terminal FAIL (no auto-resubmit — GPU-hours) |

---

## D1 — Head shape: a separate `POST /train` endpoint + its OWN topic (not a field on the stage trigger)

- **`POST /train`** on lance-ray (the compute-adjacent head service, same `require_dapr_token`
  guard as `/produce` and `/ingest-media`). Body:
  `{"model": "<name>", "features": [{"dataset": "...", "version": <int|null>}], "config": {...}}`
  → `202 {"token": ...}`. An omitted `version` pins to the LATEST at submit time — the pin is
  resolved at the head and threaded through, never left floating (reproducibility).
- **Own topic** (`training.jobs` via `MEDALLION_TRAIN_TOPIC`), own durable consumer + queue group.
  NOT a workload-type field on the medallion trigger: `{token, dataset, namespace}` is a
  stage-hop contract with mover semantics (block-until-done ≤ ackWait, RETRY on failure).
  Training is long-running and terminal-on-failure — overloading the stage trigger would couple
  it to mover ack windows and redelivery policy. A separate topic is a separate resiliency
  profile, and a slow training submit can never head-of-line-block a stage mover.
- Trigger payload: `{token, model, features: [{dataset, version}], config}` — pointers only,
  never data (the claim-check invariant).

## D2 — The trainer consumer: SUBMIT-AND-ACK, never block-and-poll

`services/medallion/services/ray_submit.py` documents its own limitation: the mover blocks until
the job finishes, so anything longer than `maxDeliver × ackWait` (~2.5 min) exhausts redelivery.
That pattern is CORRECT for bounded stage transforms and WRONG for training. The trainer handler
therefore:

1. FGA-gates (D5) — deny → **DROP** (attributable, like the movers), outage → RETRY;
2. submits the training job via the shared Ray Jobs REST seam with a **deterministic
   `submission_id = ray-train-<token>`**;
3. **acks SUCCESS immediately after the submit** (or after re-attaching to an already-running
   job on redelivery — the deterministic id is the idempotency key, per the §0 bus rule).

The handler never observes completion. **The training JOB ITSELF emits its OpenLineage
lifecycle** (D3) — the same driver-emits pattern `medallion_demo.py::_emit_step` proved — so job
duration is decoupled from bus semantics entirely. Redelivery of a trigger whose job already
FAILED does **not** resubmit (unlike the stage path): training compute is expensive and a failed
run is terminal until a human (or future automation) POSTs `/train` again with a fresh token.

## D3 — Lineage shape: official facets only, spec-true

- **Job**: namespace `ray-jobs`, name `train.<model>`; the official **`JobTypeJobFacet`** with
  `processingType=BATCH, integration=RAY, jobType=TRAINING` — the discriminator vs the cascade's
  `ETL`/`TRANSFORMATION`. (`jobType` is a free-string field in the published facet schema —
  `TRAINING` is spec-legal, no invented facet needed.)
- **Run**: deterministic `runId = run_id_for("train-<token>")`; lifecycle
  `START → RUNNING×N → COMPLETE|FAIL`. Progress rides the existing custom `progress` run facet
  (`{done: epoch, total: epochs}`) so the live status board renders training progress with zero
  new UI work. FAIL carries the standard `errorMessage` facet and a BARE output (no version — no
  fabricated lineage), exactly the medallion/compaction FAIL contract.
- **Inputs**: each feature dataset with the standard `DatasetVersionDatasetFacet` pinning the
  EXACT Lance version read — the reproducibility key. The graph then answers both directions:
  `upstream(models$m)` = "what data (at which versions) trained this model";
  `downstream(silver$features)` = "which models did this bad batch contaminate" (model recall).
- **Output**: `models$<model>` with the version facet + blob-aware schema facet on COMPLETE.

## D4 — The model artifact lives in Lance: `models$<model>` (DECIDED — no external registry now)

One Lance dataset per model in a `models` namespace, one row per artifact:

| column | type | content |
|---|---|---|
| `artifact` | string | `weights` \| `config` \| `metrics` \| `card` |
| `payload` | blob (v2, 2.2, stable row ids — the shared cascade-write helper) | the bytes (inline-or-pointer) |
| `meta` | JSON | framework, metric values, epochs, the pinned feature `{dataset: version}` map |

Why Lance-native (and not MLflow/HF/registry infra): provenance stays uniform — the model IS a
dataset, so the `WROTE` edge + Lance version give **model versioning via time-travel for free**,
the CAS-validated commit path guarantees write safety, blob v2 carries GB-scale weights, and
`/reconcile` + the quality gate apply unchanged. Model promotion (`staging`/`prod`) = catalog
**tags** on the models dataset, gated by the `validator` rung on `namespace:models` — the same
promotion story as silver→gold. An external registry later is the already-built external-pointer
seam (the registered external-blob base allowlist, #92): a `weights` row can point at a registry
URL without breaking the one-identity rule.

## D5 — AuthZ: a dedicated trainer identity + rung, NOT the medallion writer rung

- **`user:service-trainer`**: `reader` on the feature stage namespaces it reads (e.g.
  `namespace:silver`, `namespace:gold`) — per-namespace, NOT warehouse-wide; and `writer` on
  **`namespace:models` only** (→ `can_create_table` there). A trainer must never be able to
  write a medallion stage, and a mover must never be able to write models — the rungs don't
  overlap.
- Seed: `warehouse parent namespace:models`, per-model `namespace:models parent table:models$<m>`
  (so humans' warehouse-reader rung cascades to models), plus the trainer grants — all in
  `scripts/seed_medallion_fga.sh` next to the mover grants.
- The trainer handler checks `can_read_data` on EVERY pinned input and `can_create_table` on
  `namespace:models` BEFORE submitting; deny → DROP before any compute is spent.

## D6 — Ray seam: shared Jobs-REST core now, KubeRay `RayJob` CR at the rask merge

- Now: extract the generic submit/re-attach core out of `submit_stage_job` (it is already
  workload-agnostic: entrypoint + env + deterministic id); training passes
  `scripts/ray_train_job.py` (baked into the ray-lance image) and SKIPS the block-poll. The demo
  tier trains a small CPU model (real features → real weights blob) proving the loop; a real
  `TorchTrainer` needs GPU nodes.
- rask merge: training becomes a KubeRay **`RayJob` CR** under Kueue (GPU quota, gang
  scheduling, long-running lifecycle owned by the operator) while stage transforms stay Ray Jobs
  REST. The trigger contract, lineage contract, and authz contract in this note DO NOT CHANGE —
  only the submit transport swaps, which is why the submit core is extracted behind one seam.

## Out of scope (explicitly)

Hyperparameter sweeps / Ray Tune (each trial = one run under a parent — needs the `parent` run
facet ingestion, parked in §9 "lineage at rask scale"); model SERVING (a consumption concern,
parked with the query engine decision); auto-retraining triggers (a `downstream`-watch automation
— future); GPU scheduling itself (Kueue's job at the rask merge).
