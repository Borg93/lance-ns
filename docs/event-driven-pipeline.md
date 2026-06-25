# Event-driven medallion — how a job completion flows across NATS

Interactive version: **`docs/event-driven-pipeline.html`** (open in a browser; click a flow tab, press
Play, use ←/→ to step). This markdown is the standalone description.

## The one idea
**NATS never watches S3 and knows nothing about Lance.** It only guarantees a *message* is durably
stored and redelivered until acked. "Did the Lance table finish landing?" is answered by the
**consumer/worker**, which:
1. *submitted* the Ray job, then
2. *polled* its status until `SUCCEEDED` (and read `ds.version` back as proof), then
3. **re-published** that fact as a *new* message (`silver.ready`) — which is the next stage's trigger —
4. and only then **acked** the original trigger.

So a "completion" is just another published message. Ray computes, NATS transports, the worker is the
bridge that turns "the write committed a new Lance version" into an event.

## Components (nodes)
| Node | Role | What it is |
|---|---|---|
| Person / client | user | Orders a job (or a scheduler / the UI does) — `POST /jobs`, returns a job id immediately |
| Job API | service | FastAPI; verifies **OIDC + OpenFGA**, then publishes the trigger to NATS |
| NATS JetStream | stream | Durable stream `MEDALLION`; subjects `medallion.*` + `lineage.events`; at-least-once, redelivery, DLQ |
| Embed worker | worker | `nats-py` durable **pull consumer** — the bridge; submits Ray jobs, owns the ack |
| Ray job | compute | Reads input Lance, computes features, writes the output Lance dataset to S3 |
| Lance · S3 | storage | RustFS (S3-compatible); append-only, immutable versions (commit = a new version) |
| Lineage svc | service | A JetStream consumer of `lineage.events`; OpenLineage → Apache AGE → the SvelteKit UI |

## Flow 1 — Job handoff (bronze → silver) — *the answer to "how does it know it finished?"*
1. **Person → Job API** `POST /jobs` — returns a job id fast; does not wait.
2. **API → NATS** `PUB medallion.bronze.ready` — server ACK = durably stored (`Nats-Msg-Id` for dedupe).
3. **NATS → Worker** — durable pull consumer fetches it; message is *in-flight*, ack pending (`ack_wait`).
4. **Worker → Ray** `submit_job(submission_id="embed-<msg-id>")` — the bridge; id makes redelivery safe.
5. **Ray → S3** `lance.write_dataset(...)` — writes *new* data files (no in-place mutation).
6. **S3 → Ray** *manifest commit* → **version 1** becomes visible atomically. **This is when it "landed."**
7. **Ray → Worker** `get_job_status → SUCCEEDED`, `version == 1`. The worker *polls* — calling
   `msg.in_progress()` to keep the NATS ack alive during the long job. **This is how it knows.**
8. **Worker → NATS** `PUB medallion.silver.ready {uri, version:1}` + `PUB lineage.events COMPLETE`,
   **then** `msg.ack()`. Publish-then-ack: a crash before the ack → NATS redelivers → idempotent re-run.
9. **NATS → Lineage** — the lineage consumer ingests COMPLETE; `(:Run)-[:WROTE {version:1}]->(:Dataset)`.

## Flow 2 — Failure → redelivery → DLQ (why nothing corrupts)
1. Deliver (attempt #1). 2. Submit Ray. 3. **Write aborts** (CUDA OOM) — Lance never commits the
manifest, so **no new version**; half-written files are orphaned, never visible (the table stays at its
last good version). 4. `status = FAILED`. 5. Worker **NAK** + `PUB lineage.events FAIL` — but **no**
`silver.ready`, so the pipeline does not advance. 6. NATS **redelivers** (same `submission_id` → the
whole idempotent job re-runs), up to `max_deliver`. 7. Exhausted → **TERM** + publish to `medallion.dlq`
for an operator. Nothing is silently dropped; nothing downstream sees a partial write.

## Flow 3 — Lineage rides the same bus (todo P2 #14)
Workers publish OpenLineage `START`/`COMPLETE`/`FAIL` to `lineage.events` instead of POSTing HTTP. The
lineage service is a durable JetStream consumer (decoupled, replayable, crash-safe), MERGEs into Apache
AGE, and the SvelteKit UI renders it — the same graph you watch in the live demo, just fed by events.

## How this maps to the current demo
Today `scripts/medallion_demo.py --step N` is the **synchronous** version: it does the Lance write *and*
emits OpenLineage inline. The event-driven version keeps the exact same Lance ops and OpenLineage
payloads, but splits them across NATS: the `--step` becomes a published trigger, the write becomes a Ray
job a worker submits, and "done" becomes a published `*.ready` event. **Where Dapr fits:** the
idempotent batch legs (bronze→silver, silver→silver) need only NATS + Ray. The human-ordered,
multi-step silver→gold *promotion* uses a **Dapr Workflow** (durable, resumable); auth is checked once at
the scheduling edge (OIDC) + per-activity (OpenFGA, token-independent), with the verified `sub` captured
as durable workflow input. See the chat thread / `todo.md` P2 #14, #16.
