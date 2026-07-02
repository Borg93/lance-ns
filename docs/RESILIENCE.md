# Resilience & failure modes (chaos-tested)

What happens when a service goes down, can we get corrupted state, and how do we recover. Each claim
below was verified by **pulling a live service** on the kind cluster and observing recovery.

## The core guarantee: at-least-once + idempotent → no corruption, no loss (within bounds)

The event-driven path is `catalog --Dapr publish--> JetStream (LINEAGE/MEDALLION streams) --> subscriber`.
Two properties make it safe:

1. **Durable buffer.** Both streams use **Limits retention** (messages persist after ack, up to `max-age`
   168h), so an event survives the subscriber being down.
2. **Idempotent ingest.** The graph **MERGEs on `run_id`**; the medallion run_id is derived from the
   trigger token. So redelivery / replay of the same event is a **no-op** — never a duplicate, never
   corruption. The worst failure mode is *under-reporting* (a lost event), never a corrupt or doubled one.

## Chaos experiments (all recovered with zero loss)

| Experiment | What happened | Result |
| ---------- | ------------- | ------ |
| **Pull `lineage` (scale 0), publish 3 events, restart** | events buffered in JetStream (70→73); on restart the **ephemeral consumer replayed** them | **3/3 ingested** — no loss |
| **Kill `AGE` (Postgres) mid-ingest, restart** | ingest returned `RETRY`; Dapr redelivered per `backOff` until the DB was back | **ingested on redelivery** — no loss |
| **Pull `bronze-to-silver` mover, fire `/produce`, restart** | cascade **stalled at bronze** (trigger buffered in the MEDALLION stream); restart replayed it | **cascade resumed to gold** |
| **Idempotency** (replays re-deliver old events) | fixed `run_id`s re-MERGE | `gaptest1` has **exactly 1** producer run — no duplication |

So: **a service going down delays the pipeline; it does not lose or corrupt data.** Transient dependency
failures recover via Dapr `RETRY` (ackWait 30s, maxDeliver 5, backOff `30s,60s,120s,300s` — the first
backOff step IS the effective ack window per NATS consumer semantics, so it must not undercut the slowest
handler; the ~8.5 min total window covers a realistic dependency blip).

> ⚠️ **Semantics changed by the §2 bus fixes (re-verify live on next deploy).** Each subscriber now has
> its **own** pubsub component with `queueGroupName=<app-id>` (replicas = competing consumers → single
> delivery per app; scaling movers past 1 is now safe) and a split `deliverPolicy`: **`all` for lineage**
> (the restart-replay row above still holds — replay into the idempotent MERGE is the durability story)
> but **`new` for the cascade head + movers** — a full-stream replay there would *re-fire every cascade
> in the retention window* on each restart. Consequence: the third row changes — a trigger published
> while a mover is down **beyond the ephemeral consumer's inactivity window** is no longer replayed on
> restart (quick restarts rejoin the surviving queue-group consumer and keep its pending messages). The
> stalled stage is a documented gap (#3 below) until the durable PULL consumer lands.

## Where it CAN bite — the real gaps (honest)

1. **The catalog outbox gap (the #1 weakness).** The catalog emits lineage **inline-awaited + best-effort**
   *after* the Lance write commits to S3 (`services/catalog/core/lineage_emit.py`) — awaited (not a
   BackgroundTasks fire-and-forget) so the event reaches the durable Dapr/JetStream transport before the
   response returns, but its errors are swallowed so a lineage outage never fails the write. If the catalog
   crashes (or its sidecar is down) **between the S3 write and the publish**, the data exists on storage but
   **the lineage event is lost** — the graph under-reports that write. No corruption, but a provenance hole.
   *Mitigation (shipped):* the **B4 storage→graph reconcile** back-fills exactly this loss mode — a Dapr-cron
   sweep reads on-disk Lance versions and stamps any write the graph is missing (`/datasets/{name}/reconcile`
   + `services.lineage.reconcile`). *Full fix:* a transactional outbox, or make the **Ray job the durable
   producer** (it owns the write + the emit) — the documented direction ([`FLOW.md`](FLOW.md) §7, [`RASK-INTEGRATION.md`](RASK-INTEGRATION.md)).

2. **No dead-letter queue; `maxDeliver=5`.** A genuinely poison message (always `RETRY`, not malformed)
   is dropped from the *consumer* after 5 deliveries (~8.5 min of backOff) with **no DLQ**. Limits
   retention keeps it in the *stream*, so the lineage consumer (`deliverPolicy: all`) re-sees it on
   restart — but an outage longer than the retry window means the event isn't ingested **until a
   restart**. *Fix:* set a Dapr `deadLetterTopic` + an operator drain, and move to a **durable PULL
   consumer**.

3. **The lineage consumer still full-stream-replays on restart; the trigger consumers now miss instead.**
   Post-§2 the trade-off is explicit per subscriber: lineage keeps `deliverPolicy: all` (each restart
   replays the entire retained stream into the idempotent MERGE — O(stream size) load, zero loss), while
   the cascade head + movers use `new` (no restart storm, but a trigger published while a mover is fully
   down is **missed** — that batch stalls until the next raw write or a manual re-fire; the reconcile
   cron back-fills dataset *writes*, not triggers). *Fix for both:* a **durable PULL consumer** that
   resumes from the last ack (the documented production-hardening follow-up).

4. **Best-effort durable feed.** The `/events` feed table write is best-effort (logged on failure); the
   AGE graph is authoritative. The feed can lag the graph — visibility, not correctness.

## Bottom line

- **Corruption:** not possible on the event path — idempotent MERGE on `run_id`.
- **Loss:** only at the catalog outbox gap (crash between S3 write + publish). Everything downstream of a
  successful publish is durable + replayed.
- **Recovery:** automatic — `RETRY` for transient faults, JetStream buffer + replay for downed services.
- **Hardening roadmap (for prod):** durable PULL consumer (resume-from-ack) · Dapr `deadLetterTopic` ·
  transactional outbox / Ray durable producer. None are needed for the demo; all are needed at scale.
