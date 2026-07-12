# The data contract — what it is here, how it's enforced, and what is honestly not yet

**Status: DOCUMENTED 2026-07-11 (§9 P1 — previously existed only in chat).** Answers four
questions in order: what a data contract is, how THIS platform's works, whether it's prod-ready
(honest split), and how it relates to Dapr/NATS and to Lakekeeper. Every claim cites shipped code.

## 1 · What a "data contract" is

The agreement between a data **producer** and its **consumers** about what the data looks like and
how it may change: the schema, the versioning/evolution rules, the quality guarantees, and how a
consumer can rely on all three without talking to the producer's team. In classic stacks this is a
separate ARTIFACT — an Avro schema in a Kafka schema registry, a dbt model contract, a
`datacontract.yaml` — that some gate validates against.

**This platform deliberately has no schema registry.** The contract is *structural*: it falls out
of three properties the storage and bus already have, plus three enforcement points that check it.

## 2 · Our contract, in one table

| Layer | The contract | Where it lives |
|---|---|---|
| **Storage** | **The Lance manifest IS the schema; the version IS the handshake.** Every write commits an immutable, numbered version whose manifest embeds the full schema — data is self-describing, so there is nothing separate to register or drift from. A consumer that pins `(dataset, version)` gets bit-identical data + schema forever (time travel). | Lance format itself; CAS commit (put-if-not-exists) validated live against RustFS — `tests/e2e/test_object_store_cas_e2e.py`, verdict in `docs/DURABILITY.md` |
| **Bus** | **Events carry POINTERS, never data** (claim-check): a stage trigger is `{token, dataset, namespace}`, a train trigger is `{token, model, features:[{dataset, version}], config}`. The OpenLineage facets' `_schemaURL`s ARE the event-shape contract — official spec URLs, pinned in code and drift-tripwired in tests. | `services/medallion/services/{transform,train}.py`; facet pins in `services/medallion/schemas/events.py` + `scripts/ray_train_job.py` (equality-pinned by `tests/unit/test_train_job.py`) |
| **Identity** | One string threads all planes: `table:<id>` is the catalog id, the OpenFGA object, and the lineage graph node — so the contract's subject is never ambiguous. | catalog + `model.fga` + AGE ingest |

The **handshake in practice**: a mover reads its upstream at the version the trigger's lineage
event recorded, writes downstream producing a NEW version, and emits that version in the
`DatasetVersionDatasetFacet`. Training sharpens it further — `POST /train` resolves omitted
versions to LATEST **at the head** and the job reads ONLY pinned versions (`docs/RAY-TRAIN.md`
D1; unit-proven: pinned-v1 means ≠ LATEST means in `tests/unit/test_train_job.py`).

## 3 · The three enforcement points (who checks the contract, when)

| When | Gate | What it enforces | Code |
|---|---|---|---|
| **Promotion-time** | Quality gate (`MEDALLION_QUALITY_ENABLED`) | the DATA is good enough to promote: `row_count_positive` + `not_null(key_column)` + `blob_resolves` per blob column (2026-07-12: one real byte read from the first+last rows' payloads — catches a dangling external pointer/bucket wipe AT promotion instead of at first downstream read); a failure still emits the run + its `dataQualityAssertions` facet (auditable) but BLOCKS the next stage trigger — a bad batch cannot cascade | `services/medallion/services/quality.py` |
| **Access-time** | OpenFGA (fail-closed) | WHO may read/write/promote: concentric owner⊇writer⊇reader rungs + the separate `validator` rung for promotion; movers/trainer check as their OWN service identities before spending compute (deny → DROP) | `services/common/fga.py`, `handle_train_trigger`, mover gates |
| **Drift-time** | B4 reconcile (cron) | the GRAPH matches STORAGE: back-fills Lance writes whose lineage event was lost; flags `missing_on_storage`; and probes blob-POINTER health (2026-07-12: `dangling_blob_columns` — an external payload deleted after promotion changes no Lance version, so only the 1-byte probe sees it; same shared probe as the quality gate) | `services/lineage/api/v1/endpoints/reconcile.py` |

Plus edge validation where the bus meets code: consumers treat the bus as a wider trust surface
than token-guarded heads and DROP malformed triggers rather than repair them (version-less
features, path-unsafe names, oversized/non-dict config — `services/medallion/services/train.py`).

## 4 · Is it prod-ready? The honest split

**Enforced today and proven (unit and/or live):**
- Immutable versions + CAS commits — the storage half of the contract rests on
  put-if-not-exists, and that was VALIDATED against RustFS (3-tier contended-write harness, all
  green — `docs/DURABILITY.md`). This is the strongest link.
- Pinned-version consumption for training (D1), quality-gated promotion, FGA gates, reconcile
  back-fill, strict consumer-edge validation — all shipped with tests.
- **Additive** schema evolution is safe *by construction*: `add_columns` makes a new version;
  old versions stay readable; per-version schemas ride the lineage `WROTE` edge.

**NOT yet prod-grade (tracked, deliberate):**
- **Freshness is the second known gap (2026-07-12).** A complete contract also promises arrival
  cadence — a 3-day-stale silver is as broken for a consumer as a missing column. Today the run
  board and the transitions metric make staleness *visible* but nothing *asserts* it; the planned
  fix rides the reconcile sweep (compare latest-write age against a per-stage freshness budget,
  WARN like dangling blobs). Tracked in todo_fable §9.
- **Breaking changes are the known gap.** A producer renaming/dropping a column a downstream
  reads is caught only at RUNTIME (the mover's transform fails → RETRY → stall) — not at
  promotion time. The fix is the §9 per-project **schema declaration** item (declare expected
  columns; the quality gate asserts they landed; reconcile flags undeclared writes) — that turns
  a runtime stall into a pre-promotion contract violation. Un-built by decision, tracked in
  `todo_fable.md` §9.
- **The claim-check rule is convention + spot-enforcement, not a universal guard.** The train
  path caps config at 8 KiB (head AND consumer); but there is no payload-size guard at EVERY
  publish site yet (§9 P1, open), and no cap on facet metadata bloat for thousand-column tables
  (§9 P2, open). NATS's ~1 MB message limit is the physical backstop.
- **Quality gate is demo-tier**: two assertions (row count, key non-null). Real deployments add
  domain assertions (and the §9 P2 "blob pointer resolves" check).

## 5 · What Dapr and NATS actually enforce (and what they don't)

Dapr and NATS do **not** enforce the data contract — they enforce the **delivery contract** that
makes the data contract *checkable*:

- **NATS JetStream** guarantees at-least-once delivery on durable streams (`LINEAGE` /
  `MEDALLION` / `TRAINING`), `maxDeliver=5` with backoff, 168h Limits retention. Its ~1 MB
  message bound is *why* the claim-check rule exists: the bus physically cannot carry data, so
  events must be pointers — a contract enforced by constraint.
- **Dapr** supplies the pub/sub abstraction, the SUCCESS/RETRY/DROP ack semantics, the
  app-api-token on subscription routes (a forged trigger can't spend compute), and the 30s ack
  window that shapes every handler (work fast or submit-and-ack).
- The **data** contract itself is enforced by Lance (manifest schema + CAS commit) and by the
  services at the three gates above. The bus's job is narrower: the trigger arrives at least
  once, and because every handler is idempotent (deterministic tokens/run-ids/submission-ids),
  at-least-once is as good as exactly-once.

## 6 · Is this the same as Lakekeeper?

No — related species, different format and bigger scope on our side:

| | **Lakekeeper** | **this platform** |
|---|---|---|
| What it is | Apache **Iceberg** REST catalog (Rust) | **Lance** REST catalog + lineage + governance + medallion orchestration |
| The "contract" | the Iceberg spec: snapshots, schema evolution via column IDs, hidden partitioning — metadata JSON managed by the catalog | the Lance manifest + immutable versions (§2) — self-describing storage, catalog is a thin adapter |
| AuthZ | OpenFGA (same choice — we studied theirs) | OpenFGA, threaded through the SAME `table:<id>` identity as lineage |
| Lineage | none | OpenLineage → AGE graph, column-level, reconcile back-fill |
| Data movement | none (catalog only) | the event-driven medallion cascade + Ray compute + training are IN scope |
| Data contracts as a product | no — like us, the table format IS the contract | no registry either; adds the quality/FGA/reconcile gates on top |

We deliberately mined Lakekeeper for patterns (`docs/SYSTEM-SKETCH.md` has the full diff): vended
credentials with `expires_at_millis`, idempotency keys, scoped event emission — adopted; their
route-enum conformance markers — skipped. Neither system is a "data contract product" like a
schema registry; the difference is that Iceberg's contract semantics (column-ID-based evolution)
are ecosystem-standardized, while ours lean on Lance's manifest + our own gates — which is why
the breaking-change detector in §4 is OUR item to build, not something the format gives us.

## Related docs
[`ARCHITECTURE.md`](ARCHITECTURE.md) · [`DURABILITY.md`](DURABILITY.md) (CAS validation) ·
[`RAY-TRAIN.md`](RAY-TRAIN.md) (D1 pins, D4 registry) · [`RESILIENCE.md`](RESILIENCE.md)
(delivery semantics) · [`SYSTEM-SKETCH.md`](SYSTEM-SKETCH.md) (Lakekeeper diff) ·
`todo_fable.md` §9 (schema declaration + claim-check hardening, the tracked gaps)
