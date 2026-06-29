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
mover, which produces bronze. (In production `lance-ray` is a real Ray Data job writing a Lance table +
emitting lineage; here it's a dummy emitter — no heavy compute — which is all the event-driven demo needs.)

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
- **Metrics** (PromQL): `medallion_stage_transitions_total{transition}` counts each hop
  (`source->raw`, `raw->bronze`, `bronze->silver`, `silver->gold`).

## Why event-driven (vs. the old `scripts/medallion_demo.py`)

The script driver runs the stages in-process, sequentially. The event-driven version makes each stage an
independently deployable, independently scalable service that reacts to its upstream's completion — the
real microservices shape: a slow silver stage can't block bronze ingestion, each stage retries on its own
(Dapr redelivery + idempotent emit), and the whole flow is observable as one trace without any glue code.
