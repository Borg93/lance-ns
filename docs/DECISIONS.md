# DECISIONS — consolidated architecture decisions

Extracted from the retired `GOAL-prove-it.md` / `DESIGN-catalog-parity.md` progress docs so code + docs
can cite a permanent record. Those two files were goal-tracking logs; the *decisions* they contained are
still load-bearing and are captured below, one section per cited label. Headings preserve the original
labels (`P1.1`, `#38b`, `#3-A`, …) so existing citations resolve to a stable anchor here.

The two source docs recorded a much larger body of progress prose (proof logs, live-drive transcripts,
audit dispositions). Only the parts other files actually cite survive here — the durable decision plus its
rationale, not the day-by-day tracking.

---

## P0.1 — why e2e_stack.sh exists (live-verify honesty)

**Decision.** CI boots a real kind stack and runs the e2e suites (outbox, warehouses, multibase,
client-direct, CAS, governance) via `scripts/e2e_stack.sh`; a condition that cannot be proven by a grep,
a CI test, or a live assertion with a durable artifact is **not a condition, it is a claim**. The runner
additionally **fails if any test SKIPS**.

**Rationale.** Every "live-verified" claim used to rest on manual terminal runs while CI ran
`pytest -m "not e2e"`. The e2e-stack job existed but had never once gone green — a silent
`--set web.enabled=false` on a key that did not exist wedged it in `ImagePullBackOff` on every run. A CI
job that has never been green is a decoration, not a proof; and a green tick over a suite that never ran
(two suites skipped themselves on env-var name mismatches) actively buys false confidence.

## P0.2 — claim-lint (the grep-provable invariants)

**Decision.** The recurring bug classes are pinned as mechanical tests in `tests/unit/test_invariants.py`,
run in CI: no bare lineage publish bypasses the outbox (the #4 uniformity invariant), every chart-injected
env var is read somewhere in `services/`, every FGA relation the code writes/checks exists in the compiled
`model.json`, and every `--set` key our scripts pass is defined in `values.yaml`.

**Rationale.** Each of these was violated silently before it was grep-proven (3 of 4 publishers bypassed
the outbox; a `--set` on a non-existent key made an unconfigured stack *look* configured). The lint is the
writing-python T6 "test every similar case in the same change" rule mechanized, so the class cannot regress.

## P1.1 — outbox observability (the four signals)

**Decision.** The lineage outbox is an external boundary (S3 + pub/sub) and carries the four golden
signals — counters for staged / drained / poison plus gauges for outbox **depth** and **oldest-age** —
exported OTLP-direct to GreptimeDB, with a Perses alert on `depth>0` sustained.

**Rationale.** Without depth/age a leaking outbox is invisible and every durability property is
unobservable. A gauge pinned at 0 is indistinguishable from a *stuck* one, so the alert signal was driven
live (survivors staged → depth rises → relay drains → depth falls) and read back out of GreptimeDB, not
merely asserted to be emitted.

## P1.2 — bounded, oldest-first outbox drain

**Decision.** The reconcile drain caps how many staged events it processes per tick, **oldest-first**,
carrying the remainder to the next tick (`outbox_drain_limit`).

**Rationale.** The drain previously `list()`ed the entire outbox prefix into memory under the single-flight
lock, so a backlog could OOM or stall the tick. Bounding it keeps each tick's memory and work finite while
still guaranteeing every survivor is eventually drained (a unit test drains N > cap across two ticks).

## P2.1 — single-base cascade write

**Decision.** The medallion/Ray cascade writes `mode="overwrite"` to **one** root; Lance multi-base (#3-B)
stays REST-create-only and is deliberately **not** wired through the mover write path — WONTFIX, stated as
a boundary in the `compute.py` mover docstring, not an accidental omission.

**Rationale.** Base registration (`initial_bases`) is create-time-only while the cascade is overwrite-only,
so distributing it would need first-write-vs-overwrite base state threaded through the movers — and a bare
overwrite that doesn't re-send the base silently concentrates fragments in the primary root (a live proof
flaky by construction). The pipeline already distributes at the *zone* level, and no cascade stage table is
at the per-table multi-base scale. Revisit only when a real gold/training table demonstrably exceeds
single-bucket throughput or needs cross-region DR **and** the Ray distributed-write path lands.

## #16 — Dapr Workflow for silver-to-gold promotion

**Decision.** The idempotent batch legs (bronze→silver, silver→silver) need only NATS + Ray, but the
human-ordered, multi-step silver→gold **promotion** uses a Dapr Workflow (durable, resumable). Auth is
checked once at the scheduling edge (OIDC) and again per-activity (OpenFGA, token-independent), with the
verified `sub` captured as durable workflow input.

**Rationale.** A promotion is a long, human-gated, resumable sequence that must survive process restarts and
re-authorize each step independently of the original request token — exactly the durable-workflow fit,
whereas the idempotent batch hops do not warrant it.

## §7a — live-verification residuals

**Decision.** A bounded set of provenance-visibility residuals is tracked (not corruption, not blocking):
overwrite leaves stale column nodes on the reused dataset id; reconcile false-flags a *deliberately* dropped
table as `MISSING_ON_STORAGE` from a stale `source_uri`; column-level lineage is emitted as a facet but not
yet stored as graph nodes/edges. Also tracked: the governed-union live evidence predates the §7a hardenings
and wants a re-run (`make e2e-governed-union`, subsumed once e2e is in CI).

**Rationale.** These are known, bounded lifecycle-emit gaps recorded so they read as deliberate residuals
rather than unproven claims. Rename on the `dir` backend is 501 (emits nothing) — moot, not a gap.

## §9 — feature gaps (the open backlog)

**Decision.** The net-new feature backlog beyond the shipped parity work, kept visible as future work:
per-project **schema declaration** (see below), **claim-check** payload-size guards at every publish site
(P1) and facet-bloat caps for wide tables (P2), the **pointer-aware GC** posture and broader orphan-janitor
drive, and the **run-INPUTS API** (a run's input version pins are reachable only via raw Cypher today —
needed for "which feature versions trained this model").

**Rationale.** Each is a real capability gap, un-built by explicit decision under the batch+training compass
(no query engine now), logged as tracked work rather than silently dropped.

## §12 — prod-hardening backlog (native switches off)

**Decision.** Several native k8s/Dapr security switches are deliberately **off** in the dev baseline,
deferred to prod in a specific fix-order: **L3 network default-deny** first (today any pod can reach the
OpenBao secret store), then **least-privilege ServiceAccounts** (~13 pods run on `default` with a mountable
API token), then **infra-pod securityContext** (the app tier is already hardened), then **Pod Security
Admission** enforcement.

**Rationale.** The don't-reinvent audit confirmed we reinvent nothing k8s/Dapr owns (zero code to delete);
these are un-flipped native switches, not missing code, and they are footgun-sequenced — default-deny egress
without a kube-dns allow bricks the cluster, and restricted PSA would reject `lineage`/`openfga-migrate`
until their root init containers are hardened. kind's default CNI ignores NetworkPolicy, so they cannot even
be validated in the dev baseline.

## #115a-c — Ray TRAIN vs Ray DATA (one platform, both workload classes)

**Decision.** The platform hosts **both** batch/ETL (the medallion cascade — the Ray *Data* shape) and
long-running **training** (Ray *Train*) as distinct workload classes with different runtime treatment
(bounded stage-transform vs fire-and-track submit+ack; RETRY vs terminal FAIL on GPU-hours; `ETL` vs
`TRAINING` jobType) but **one** provenance model, **one** authz model, **one** storage substrate. `POST
/train` gets its own topic (not a field on the stage trigger). #115a (head + topic + submit-and-ack
consumer), #115b (`ray_train_job.py` + registry publish + lifecycle lineage) and #115c (seed grants) all
landed at the unit tier.

**Rationale.** Training and ETL are genuinely different workload classes, but forking the governance /
lineage / storage model across them would be the wrong seam. Open residual: the chart values passthrough and
the live kind drive.

## blob-pointer-lifecycle GC — never collect referenced artifacts

**Decision.** GC of model/artifact objects (`models/<m>/<token>/` left by crashed runs) must **never**
collect an object still referenced by the registry; only orphaned crashed-run tokens are swept.
`scripts/model_artifact_janitor.py` ships dry-run-by-default with a `referenced ⇒ never-collected` unit pin.

**Rationale.** Pointer-aware GC is the safety property that keeps background maintenance from deleting live
data. The live drive of the broader pointer-aware posture (external-base blobs, AutoCleanupConfig-vs-sweep)
remains a §9 residual.

## schema-declaration + claim-check hardening

**Decision.** Two data-contract hardenings. (1) **Schema declaration** — movers declare `requiredColumns`;
the quality gate asserts the declared columns landed (blocks promotion, the write still commits + audits a
FAIL run) and the reconcile patrol re-checks the same declarations estate-wide, so a dropped/renamed declared
column becomes a *pre-promotion contract violation* instead of a runtime mover stall. Additive evolution is
never blocked; no declaration (default) = byte-identical gate. (2) **Claim-check** — events must be pointers,
not payloads; the train path caps config at 8 KiB (head + consumer), but a payload-size guard at *every*
publish site and a facet-bloat cap for thousand-column tables are still open.

**Rationale.** NATS's ~1 MB message bound is the physical backstop that makes claim-check a constraint rather
than a preference. Breaking-change detection is *our* item to build because Lance's manifest gives immutable
versioning but not Iceberg-style column-ID evolution semantics — the format does not give it to us.

## AGE-on-CNPG vs Lance-native-graph (the lineage-store decision)

**Decision.** The lineage graph needs the Apache **AGE** extension, but CNPG runs stock Postgres — so the
rask fold-in must pick one of: (a) point CNPG at a custom Postgres-with-AGE image, (b) keep AGE as a separate
operand, or (c) execute the pivot to move lineage to a **Lance-native graph**, which drops the AGE/Postgres
dependency entirely.

**Rationale.** This is the load-bearing pre-merge decision — it blocks the chart flip and shapes the CNPG
database list. The Lance-native-graph pivot is the option that *removes* an operand rather than adding a
custom image-build; it must be decided before/early in the merge.

---

## Control-plane vs data-plane split (the prod cut)

**Decision.** *Authorize the manifest commit and the provisioning ops; let bytes go direct to the store under
scoped, expiring vended creds — never through the server.* Four planes:

| Plane | Operations | Authorized by |
|---|---|---|
| **Admin / provisioning** | create tenant/team, create warehouse (provision bucket, register `base_uri`, stamp 2.2 + stable-row-ids), create/drop namespace, manage FGA model/tuples | platform admin (`project` / `warehouse` / `namespace` admin relations) |
| **Control / coordination** | the manifest-version commit (the single serialization point), rename, declare/deregister, branch/tag, restore, clone, credential vending, DDL | table-scoped FGA (`can_commit`/`can_promote`/…) — **authorize the commit call, not the bytes** |
| **Data** | `write_fragments` (client→bucket direct), scans/query, insert/merge/update/delete, MV refresh, blob read | data-scoped FGA (`can_write`/`can_read`) — bytes flow client↔store under vended, expiring creds |
| **Eventing** | lineage outbox → Dapr publish → consumer → AGE | trusted internal channel (Dapr → NATS) |

**Rationale.** This is exactly the Lakekeeper/Polaris cut, and the FGA model already encodes it. What a prod
control plane still lacks: a managed admin API/UI to *provision* tenants + warehouses and manage grants
(today grants are enforcement-only, no managed surface) and the physical bucket-per-warehouse to back it —
see #3-A.

## #3-A — per-warehouse bucket (physical multi-tenancy)

**Decision.** A warehouse is a runtime-provisioned, **physically separate bucket** (one tenant → one bucket;
isolation — Lakekeeper parity), provisioned + governed through an admin control-plane API, not the shared
`lance-catalog` bucket by prefix. Warehouse-create provisions the bucket, registers it as the warehouse
`base_uri`, seeds FGA (`warehouse:<id>` parent `project:<project>`, caller = owner), and stamps create-time
policy (`data_storage_version=2.2` + stable-row-ids) at the fresh-bucket boundary. Warehouse-aware routing
resolves the request's top-level namespace binding to that warehouse's rooted connection, **falling back to
the default root when unbound** (backward compatible).

**Rationale.** A dataset is self-contained under one root (relative refs), so bucket-per-warehouse needs zero
manifest surgery, and the fresh-bucket boundary is the clean seam to enforce the 2.2 + stable-row-id policy.
Shipped + audit-hardened (a CRITICAL cross-tenant takeover fixed among 5 isolation holes), live-verified on
kind (distinct buckets; table in A physically absent from B; non-project-admin 403).

## #3-B — Lance multi-base (throughput, tiering, DR)

**Decision.** Expose `data_bases` so **one table can span N buckets** via `base_paths[]` + `base_id`
(round-robin writes, fan-out reads) while staying strictly relative-path portable and governed per-base. The
security crux: `data_bases` is restricted to an **allowlist** (`LANCE_MULTIBASE_DATA_BASES`) — an off-list
base is rejected 400 — so a caller cannot point at an arbitrary bucket to exfil/write; `base_store_params`
are runtime-only (no credential persistence).

**Rationale.** This is the differentiator (the Uber pattern): Iceberg (absolute paths) and Delta (hybrid,
loses portability on shallow-clone) can't do it cleanly; Lance keeps relative-path portability **and**
multi-location. #3-B is throughput/DR/tiering and is **orthogonal** to #3-A's isolation — do not conflate the
two axes. Shipped + audit-hardened; a single small create redirects its fragment into a data base (not the
primary root) and round-robin spread grows with fragment count.

## #38b — MV-lineage is WONTFIX (no source_tables)

**Decision.** The materialized-view path emits **no** OpenLineage, and this is WONTFIX with the current code.
Do **not** fabricate an MV lineage edge from the view's own id/output_schema — that names the OUTPUT, not its
sources, a false provenance claim.

**Rationale.** The MV receives its source only as an opaque `source_query` blob the namespace server stores
without interpreting; there is no structured list of source tables to name in a lineage event (unlike the
cascade, where the source is known from mover settings). Unblocking requires **either** a SQL/plan parser to
extract source tables (the repo has none) **or** an API/contract change adding a structured
`source_tables: list[str]` alongside `source_query`. Parked until an MV consumer needs it. The governance
half is already done: `create_materialized_view` seeds FGA ownership on the `materialized_view` type.

## Lance-spec landmines

**Decision.** Format-spec constraints any catalog/pipeline code must honor (each a silent footgun):

- `enable_stable_row_ids` is **create-time-only** (silently no-ops later) → verify the `FLAG_STABLE_ROW_IDS`
  bit rather than trusting the request.
- `data_storage_version` is **immutable per dataset**; 2.2 is required for blob-v2 (why blob-create stays
  server-side / centralized).
- Secondary indices reference **row address, not `_rowid`**; compaction invalidates them
  (stable-row-id-for-index is experimental).
- The conflict matrix is **per-op**: `Append`↔`Append` auto-rebases, `Overwrite`/`Restore` do not — the
  commit retry loop must classify the error, not blindly retry.
- **Ref-plane mutations (tag/branch create) emit no version** → invisible to a version-tailing outbox.
- Implement to the **model files, not the prose** (`RenameTableRequest.new_table_name` /
  `new_namespace_id`, never `new_id`).

**Rationale.** Each is a case where the wrong assumption passes tests but corrupts a property — a wrong-version
table must be recreated, an invalidated index returns wrong rows, an un-tailed ref mutation is lost lineage.
Recorded so nobody "cleans them up" back into the trap.
