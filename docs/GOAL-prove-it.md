# GOAL — Prove it: finish #3/#4 for real, kill claim-drift, make DONE mechanical

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

## P2 — make #3 true for the pipeline we actually run

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

## P4 — the audit-workflow findings (reserved — folded in when wgznqpmwd lands)

Pending verdicts to triage into P-levels here:
- Dapr-native outbox + distributed lock vs our hand-rolled S3 outbox + PG advisory lock
  (CONFIRMED reinvention → migrate; REFUTED → document the justification in-code).
- Lance format conformance: row_id_lineage (row-level provenance for training — potentially the
  real multimodal differentiator), branch_tag (do our endpoints honor the spec?), mem_wal,
  transaction-conflict matrix vs our #2 assumptions.
- Skill-reference drift (all 6 skills, references read this time) + code-quality fixes.
- Event-driven integrity (hidden polling/sync coupling) + lineage completeness gaps
  (compaction/index/GC provenance; Ray-path parity).
- Claim-drift sweep results beyond the three already fixed.

## THEN (after P0–P4, the actual product direction — user-confirmed)

Multimodal retrieval + the ML loop, in this order and nothing sooner:
1. Governed k-NN `/search` over cascade-derived embeddings (native Lance `nearest`; NOT an engine).
2. Model registry + candidate→blessed promotion (task #17) with lineage to the exact dataset
   version + row-id provenance to source media.
3. Experiment tracking via OTLP→Greptime (task #18).

## DONE-definition (applies to every item above, permanently)

An item is DONE when: (1) its stated mechanical proof passes, (2) it survived an adversarial
audit and the findings are fixed, (3) the proof runs in CI — not in a terminal. "It worked when
I ran it" is not a state; it is an anecdote.
