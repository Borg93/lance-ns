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
