# Event-driven medallion pipeline

The medallion lakehouse pattern — **raw → bronze → silver → gold** — implemented as **event-driven
microservices** on Dapr pub/sub (over NATS JetStream), not a script. One trigger cascades the whole
chain, each hop emits OpenLineage (so the graph grows the DAG), and Dapr propagates the trace context
so the whole cascade is **one distributed trace**.

## Is `lance-ray` the first trigger to bronze? — Yes.

`lance-ray` is the **head of the pipeline** (a dummy Ray ingest job). It is **one hop upstream of
bronze**: on `POST /produce` it (1) emits the OpenLineage event for the `raw_events` source dataset and
(2) publishes the **first trigger**, `medallion.raw`. The `raw→bronze` mover subscribes to that trigger
and produces bronze. So:

```
                        emits raw_events lineage
   POST /produce ─▶ lance-ray ──────────────────────▶ (lineage svc → AGE)
   (you/cron)         │  publishes medallion.raw  (the FIRST trigger)
                      ▼
              ┌─────────────────┐   medallion.bronze   ┌───────────────────┐   medallion.silver   ┌─────────────────┐
              │  raw→bronze     │ ───────────────────▶ │  bronze→silver    │ ───────────────────▶ │  silver→gold    │
              │  (ingest_events)│                      │  (embed_features) │                      │ (aggregate_gold)│
              └────────┬────────┘                      └─────────┬─────────┘                      └────────┬────────┘
        emits          │ raw_events → bronze$events              │ bronze$events → silver$features         │ silver$features → gold$catalog
        lineage ───────┴──▶ (lineage svc → AGE DERIVED_FROM edge) every hop; the lineage DAG ends up:      ▼
                                                                                              (terminal — no next trigger)

   resulting lineage DAG:   raw_events ─▶ bronze$events ─▶ silver$features ─▶ gold$catalog
```

`lance-ray` does **not** produce bronze itself — it produces `raw_events` and *triggers* the `raw→bronze`
mover, which produces bronze.

### Does the cascade produce real data, or just lineage?

Both modes, by a flag. **Default off** (`MEDALLION_COMPUTE_ENABLED` unset): the producer + movers are
pure **emitters** — they grow the lineage DAG but write no data (all the event-driven *choreography* demo
needs). **On**: each stage runs the **fake-Ray compute** (`services/medallion/services/compute.py`) — a
REAL in-process Lance write: `lance-ray` seeds `raw_events`, then each mover reads its upstream Lance
dataset, stamps a `stage` provenance column, and writes the downstream dataset — so the whole loop produces
**actual versioned data** and the emitted OpenLineage carries the **real** Lance version (not a hardcoded
`1`). This is the **lance-ray seam**: the exact `read → transform → write → version` contract a
distributed Ray Data job (`lance-ray` on rask's KubeRay) swaps into in production; in-process here so the
loop is end-to-end testable without a Ray cluster (`tests/unit/test_medallion_cascade.py` runs the full
raw→gold cascade and asserts both the data and the `DERIVED_FROM` chain).

## The services (all share the catalog image; different entrypoint)

| Service | App-id | Module | Subscribes | Publishes |
| ------- | ------ | ------ | ---------- | --------- |
| **lance-ray** (producer) | `lance-ray` | `medallion.producer:app` | — (`POST /produce`) | `medallion.raw` + raw lineage |
| **raw→bronze** | `raw-to-bronze` | `medallion.mover:app` | `medallion.raw` | `medallion.bronze` + lineage |
| **bronze→silver** | `bronze-to-silver` | `medallion.mover:app` | `medallion.bronze` | `medallion.silver` + lineage |
| **silver→gold** | `silver-to-gold` | `medallion.mover:app` | `medallion.silver` | — (terminal) + lineage |

The 3 movers are the **same module**, differing only by `MEDALLION_*` env (from/to dataset, sub/pub
topic, operation, author) — see `chart/values.yaml` `medallion.movers`. Triggers ride a dedicated
`MEDALLION` JetStream stream (`medallion.>`); the OpenLineage events ride the existing `LINEAGE` stream.

## Promotion gates — who *may* promote, and whether the data is *good enough* to

A stage moves data forward (fires the next trigger) only when it passes **two independent, opt-in gates** —
the distinction between a *registered validator that gates movement* and the *event-driven transform itself*:

| Gate | Flag | Question | Mechanism | Fail action |
| ---- | ---- | -------- | --------- | ----------- |
| **Authorization** | `MEDALLION_FGA_ENABLED` | *May this identity promote?* | the mover CHECKs OpenFGA as its **own service identity** — silver→gold needs `can_promote` (validator rung), the others `can_create_table` (writer) | `DROP` (redelivery won't grant the role) + `medallion.stage.denied` |
| **Data quality** | `MEDALLION_QUALITY_ENABLED` | *Is the produced data good enough?* | after the compute writes the downstream dataset, the mover runs cheap, exact assertions on it (`row_count_positive`, `not_null` on the key column) via `services/medallion/services/quality.py` | `DROP` (deterministically bad) + `medallion.stage.quality_blocked`; the failed run + its `dataQualityAssertions` facet are **still emitted** so the bad batch is auditable in lineage |

Both gate the **same act** (promotion) from different angles, and both compose: a stage promotes only when
it is *authorized* **and** the data *passes quality*. The quality gate requires compute (there is no data to
check otherwise). A quality block is recorded on the `WROTE` edge as `quality_passed=false` *with* the real
version, so `producers()` shows exactly which batch was stopped and why. This is the automated **validator**
half of governance the [lineage doc](LINEAGE.md#runtime-measured-facets--declared--measured-lineage-marquez-goal-1--2)
describes; a future human-approval rung can layer on the same `quality_passed` signal without new plumbing.

## Run it

```bash
make medallion        # fire lance-ray /produce, then print gold's provenance (the cascade result)
make e2e-medallion    # the automated regression test: produce → assert gold derives from raw end-to-end
```

## What you can observe (all verified)

- **Lineage DAG** (Apache AGE): `raw_events → bronze$events → silver$features → gold$catalog`. Query
  `GET /datasets/gold$catalog/upstream` — gold transitively derives from all three upstream stages.
- **One distributed trace** (GreptimeDB `opentelemetry_traces`): a single `trace_id` spans `lance-ray`,
  `raw-to-bronze`, `bronze-to-silver`, `silver-to-gold`, **and** `lineage` — the event followed across
  every Dapr hop (the gRPC publish injects `traceparent`; each subscriber continues the trace).
- **Metrics** (PromQL): `medallion_stage_transitions_total{lance_medallion_transition}` counts each hop
  (`source->raw`, `raw->bronze`, `bronze->silver`, `silver->gold`); `medallion_stage_denied_total` and
  `medallion_stage_quality_blocked_total` count promotions stopped by the authz and quality gates.
- **Measured output** (when compute is on): each `WROTE` edge carries the runtime-measured `row_count` +
  `size_bytes` the stage actually wrote (the `outputStatistics` facet), surfaced in `producers()`.

## Why event-driven (vs. the old `scripts/medallion_demo.py`)

The script driver runs the stages in-process, sequentially. The event-driven version makes each stage an
independently deployable, independently scalable service that reacts to its upstream's completion — the
real microservices shape: a slow silver stage can't block bronze ingestion, each stage retries on its own
(Dapr redelivery + idempotent emit), and the whole flow is observable as one trace without any glue code.
