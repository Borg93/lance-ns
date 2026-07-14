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

## P4 STATUS (2026-07-14) — audit fixes: 8 landed, 3 open with precise plans

**LANDED** (each with its mechanical proof, all pushed):
- `vend_credentials` honored on describe (the ONE confirmed reinvention — generic Lance clients, incl.
  lance-ray in REST mode, previously got no credentials). Read-tier only; multi-base falls back to
  server-mediated. `449f7ac`
- **Incompatible commits are non-retryable** — our 409 said "re-read and re-commit", which after a
  concurrent Overwrite would replay fragments into a semantically different table. *Our error message was
  recommending corruption.* The existing test had PINNED that advice. `7ff1e17`
- `warehouses.py` domain exceptions (was the only module forking the RFC 9457 contract). `138d4c0`
- `dependencies.py` docstring corrected — it asserted fail-OPEN while the code fail-CLOSED. `449f7ac`
- **GC sweeps every bucket** — #3-A/#3-B buckets were invisible to GC, leaking storage forever. `02013ad`
- **Gateway hardened** + the "every Deployment" claim is now a CI-enforced loop, not prose. `18554a3`
- **rename refuses branched tables** — it was silently orphaning branches (a branch is a shallow clone
  referencing the root by ABSOLUTE path; copy+delete leaves it pointing at deleted bytes). `0acda6b`
- **GC-vs-branches: REFUTED and pinned.** The audit flagged it as an unverified danger; probed live with
  `older_than=0` — the branch survived, zero data files reclaimed. GC is branch-aware. `ff43e7b`

**OPEN — attempted, reverted, and honestly deferred (NOT quietly dropped):**

1. **Non-blob creates still pin format 2.1 / no stable row ids.** This makes `#5a`'s "DONE" **false** for
   the default path, and it is CREATE-TIME-ONLY: every ordinary table created today is *permanently*
   unable to gain row-version tracking. It also blocks `row_id_lineage` — the row-level provenance a
   training lakehouse actually needs (model → dataset version → the exact source rows).
   *Attempted:* route every create through the 2.2 path. *Reverted:* 8 tests failed, and not merely the
   one pinning 2.1 routing — **the integration tests mock `ns.create_table`**, whereas the 2.2 path calls
   `declare_table` then does a real Lance write, so a MagicMock location flows into `write_dataset`. The
   fix therefore needs the integration-test **mocking strategy rewired** (real dir-namespace + tmp_path,
   as `test_blob_create.py` already does), not a dispatch flip. That is a focused piece of work, and
   rushing it is exactly the failure mode this whole document exists to stop.
   *Next:* migrate the ~6 create-path integration tests to a real dir namespace, then flip the dispatch.
2. **`source_rowid` not carried through the cascade** — blocks row-id lineage (see above) and leaves the
   positional blob carry-forward (`compute.py` pairs rows to blobs by `range(rows)`) safe only by the
   overwrite-only convention. The format's own answer (`_rowid`) is enabled on those datasets and never read.
3. **MV lineage + rename `DERIVED_FROM` + catalog FAIL events** — the worst lineage completeness holes.
   MVs emit *nothing*; rename hardcodes `inputs: []` so it severs the provenance chain while its docstring
   claims otherwise.

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
