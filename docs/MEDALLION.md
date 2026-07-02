# Event-driven medallion pipeline

The medallion lakehouse pattern — **raw → bronze → silver → gold** — implemented as **event-driven
microservices** on Dapr pub/sub (over NATS JetStream), not a script. One trigger cascades the whole
chain, each hop emits OpenLineage (so the graph grows the DAG), and Dapr propagates the trace context
so the whole cascade is **one distributed trace**.

## Is `lance-ray` the head of the pipeline? — Yes, and it's event-driven.

`lance-ray` is the **head of the pipeline** (a dummy Ray ingest job), **one hop upstream of bronze**. It is
NOT poked by a manual RPC: `POST /produce` (with compute) seeds `raw_events` and emits ONE OpenLineage event
*announcing that write*. `lance-ray` also **subscribes** to the shared lineage topic (`/raw-arrival`) and —
only for a write to the raw dataset — publishes the first trigger `medallion.raw`. So the cascade is driven
by the raw-data **arrival event**, not the call; any raw writer (this dummy, or the catalog) that emits a
raw-write event drives it. Loop-guarded: the movers' own bronze/silver/gold events on that same topic are
ignored, so the head can't self-trigger. `raw→bronze` subscribes to `medallion.raw` and produces bronze:

```
   POST /produce ─▶ lance-ray ──emits raw_events write event──▶ lineage.events.v1 ─▶ (lineage svc → AGE)
   (any raw writer)     ▲                                              │
                        └────────── /raw-arrival subscription ◀────────┘   (reacts ONLY to a RAW write)
                                     publishes medallion.raw  (the FIRST trigger)
                                          │
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

`lance-ray` does **not** produce bronze itself — it produces `raw_events`; its `/raw-arrival` subscription
then *triggers* the `raw→bronze` mover, which produces bronze. Because the head is now a subscriber like
every other stage, the pipeline is event-driven end to end — nothing polls or waits on a timer (GOAL 4 B2).

> **`/produce` is the demo entry point, not a prod surface.** It carries no auth (it sidesteps
> `enforce_author` — a caller could trigger cascades and forge medallion provenance), so its gateway
> route is values-gated: `medallion.producer.expose` (on for the dev demo, **off in `values-prod.yaml`**).
> That closes the **external/edge** path — from the gateway, the prod head fires only from real
> raw-namespace writes via `/raw-arrival`. It does **not** close the in-cluster path: the lance-ray pod
> still serves the unauthenticated `/produce` on its ClusterIP, and this route is *not* sidecar-delivered
> so it skips `require_dapr_token`; no NetworkPolicy ships either. So an in-cluster workload can still
> reach it. Hardening that (a NetworkPolicy, or a token/authz on `/produce`) is tracked in
> `todo_fable.md` §9.

### Does the cascade produce real data, or just lineage?

Both modes, by a flag (`MEDALLION_COMPUTE_ENABLED`, chart toggle `medallion.compute`, **off by default**).
Off: the producer + movers are pure **emitters** — they grow the lineage DAG but write no data (all the
event-driven *choreography* demo needs), so the graph asserts datasets that aren't on disk (`#23` reconcile
would flag them `missing_on_storage`). **On** (`--set medallion.compute=true`): each stage runs the
**fake-Ray compute** (`services/medallion/services/compute.py`) — a
REAL in-process Lance write: `lance-ray` seeds `raw_events`, then each mover reads its upstream Lance
dataset, stamps a `stage` provenance column, and writes the downstream dataset — so the whole loop produces
**actual versioned data** and the emitted OpenLineage carries the **real** Lance version (not a hardcoded
`1`). This is the **lance-ray seam**: the exact `read → transform → write → version` contract a
distributed Ray Data job (`lance-ray` on rask's KubeRay) swaps into in production; in-process here so the
loop is end-to-end testable without a Ray cluster (`tests/unit/test_medallion_cascade.py` runs the full
raw→gold cascade and asserts both the data and the `DERIVED_FROM` chain).

> **Compute + OpenBao:** compute-on writes to RustFS with the plaintext S3 secret, so it **requires OpenBao
> off** (`--set openbao.enabled=false medallion.compute=true`). The medallion is a dummy producer with no
> OpenBao secret-fetch (unlike the catalog), so with OpenBao on it **fails fast at boot** rather than 403'ing
> at first write. The event-driven choreography (below) runs identically with compute off.

## The services (all share the catalog image; different entrypoint)

| Service | App-id | Module | Subscribes | Publishes |
| ------- | ------ | ------ | ---------- | --------- |
| **lance-ray** (producer) | `lance-ray` | `medallion.producer:app` | `lineage.events.v1` (raw filter, `/raw-arrival`) + `POST /produce` | raw-write lineage → then `medallion.raw` on a raw arrival |
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
| **Data quality** | `MEDALLION_QUALITY_ENABLED` (chart `medallion.quality`) | *Is the produced data good enough?* | after the compute writes the downstream dataset, the mover runs cheap, exact assertions on it (`row_count_positive`, `not_null` on the key column) via `services/medallion/services/quality.py` | `DROP` (deterministically bad) + `medallion.stage.quality_blocked`; the failed run + its `dataQualityAssertions` facet are **still emitted** so the bad batch is auditable in lineage |

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
