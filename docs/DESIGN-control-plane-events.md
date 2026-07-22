# DESIGN — Control-plane change-events + live frontend refresh

> **Status: PLAN (not yet built).** Awaiting review. Scope is **Lance-only** (2026-07-22 decision):
> this is an *internal* estate event stream for our own consumers + UI, not foreign-catalog interop.

## Context

`BENCH-2026-07-22.md` concluded that after the week's shipping, the **only** in-scope catalog gap left
is **control-plane change-events**: today the catalog emits **data** events (OpenLineage over
Dapr/NATS, `core/lineage_emit.py`) describing table *writes*, but nothing emits **governance/metadata**
changes — *a grant changed*, *a warehouse was deactivated*, *a policy was set*, *a namespace/table was
created/dropped*. Those mutations happen and land in the **audit trail** (GreptimeDB, #41), but there is
no real-time **subscribable stream** and no way for the console to know a change happened without a
manual reload.

Polaris 1.5 (multi-event-listener framework) and Lakekeeper (CloudEvents → NATS/Kafka) both ship this.
The value here is concrete: **the SvelteKit console refreshes itself** the instant a grant/warehouse/
policy changes (no stale access panels, no "did my revoke take?"), and internal consumers (cache
invalidation, an in-estate reaction worker) get a clean feed. The transport already exists — this is a
new topic + emit calls + a browser bridge, not new infrastructure.

## Goals / non-goals

**Goals**
- Emit a typed **`CatalogControlEvent`** on every control-plane mutation, onto the existing Dapr/NATS bus.
- **Push** those events into the browser so the affected console views **refresh live**.
- Reuse the existing emitter/transport/auth patterns (don't reinvent the bus).
- Fail-open on the *emit* side (a mutation must never fail because eventing is down) — mirror
  `lineage_emit`'s best-effort posture.

**Non-goals**
- Foreign-catalog interop / federation / Delta-Sharing (out of scope, Lance-only).
- Replacing the audit trail (that stays the durable compliance record; this is the live-notify layer).
- Guaranteed exactly-once delivery to the browser (the UI treats an event as a *refresh hint*, then
  re-reads authoritative state through the normal governed BFF path — see "Trust model").

## Architecture

Three seams: **emit** (catalog) → **bus** (Dapr/NATS) → **browser bridge** (SSE through the zone BFF).

```
mutation endpoint ──emit──▶ core/control_emit.py ──▶ Dapr pubsub.jetstream  topic: catalog.control
                                                              │
   browser ◀─EventSource─ zone BFF /events (stream passthrough) ◀─SSE─ catalog GET /v1/events/stream
                                                              ▲
                                          per-connection JetStream ephemeral consumer (CATALOG_CONTROL)
```

### 1. Emit (catalog)
- **New `services/catalog/core/control_emit.py`**, mirroring `core/lineage_emit.py`: a `ControlEmitter`
  with the same Dapr-vs-HTTP transport selection, built + torn down in the `main.py` lifespan on
  `app.state.control_emitter`, driven by `LANCE_CONTROL_EMIT_*` settings (default **off**, like lineage).
- **New event model `CatalogControlEvent`** (`services/common/control_events.py`, shared so consumers
  can import it): `{ event_id, occurred_at, action, object_type, object_id, subject, actor, extra }`
  wrapped as a CloudEvent (same envelope the lineage consumer already speaks). `action` ∈
  `grant_added | grant_revoked | warehouse_created | warehouse_activated | warehouse_deactivated |
  warehouse_bound | policy_set | policy_deleted | namespace_created | namespace_dropped |
  table_created | table_dropped`.
- **Emit sites** — publish **after** the backend/FGA mutation succeeds (never before), best-effort:
  | Endpoint (`services/catalog/api/v1/endpoints/…`) | action(s) |
  |---|---|
  | `access.py` grant / revoke | `grant_added` / `grant_revoked` |
  | `warehouses.py` create / activate / deactivate / bind | `warehouse_*` |
  | `policies.py` set / delete | `policy_set` / `policy_deleted` |
  | `namespaces.py` create / drop | `namespace_created` / `namespace_dropped` |
  | `tables.py` create / drop | `table_created` / `table_dropped` (co-emit alongside the existing lineage emit) |
  The verified `actor` comes from the OIDC token already in scope (same source the audit layer stamps),
  never self-asserted.

### 2. Bus (chart)
- Add topic **`catalog.control`** to `chart/templates/dapr-component.yaml` and a **`CATALOG_CONTROL`**
  JetStream stream/subject to `chart/templates/nats-stream-job.yaml` (alongside LINEAGE/MEDALLION/TRAINING).
- Delivery to the browser must be **broadcast** (every UI sees every event), so the SSE endpoint uses a
  **per-connection ephemeral push consumer** on the subject rather than a Dapr competing-consumer
  subscription — this is correct under 2 catalog replicas (each browser's stream is its own consumer).

### 3. Browser bridge (SSE)
- **Catalog `GET /v1/events/stream`** (new, `endpoints/events.py`): a `text/event-stream` response that
  opens a per-connection JetStream consumer on `catalog.control` and forwards each event as an SSE
  `data:` frame; heartbeats every ~15s; closes cleanly on client disconnect. **OIDC + FGA gated** — the
  estate-wide stream requires a **project admin** (same bar as the `/audit` viewer); a non-admin either
  gets 403 or (future) an object-filtered stream. Adapter is **svelte-adapter-bun**, which supports
  long-lived streamed responses, so the BFF can proxy it.
- **Zone BFF `routes/events/+server.ts`** (data + admin zones): a **streaming passthrough** to
  `/v1/events/stream`, attaching the session bearer exactly like the existing `capi/[...path]` proxy —
  no buffering, pipe the `ReadableStream` straight through.
- **Frontend client** (`frontend/packages/api/src`, shared): a small `subscribeControlEvents(onEvent)`
  wrapping `EventSource` with auto-reconnect/backoff. Each zone's root layout subscribes; on a relevant
  event it calls SvelteKit **`invalidate(dep)`** for the matching `depends()` key so only the affected
  `load` re-runs (e.g. a `grant_*` on the open table invalidates that table's access panel; a
  `warehouse_*` invalidates the warehouses list). A lightweight **toast / StatusBoard** line
  (`@rask/ui`) surfaces "access changed — refreshed".

### Trust model
The SSE frame is a **refresh hint**, not authoritative data: on receipt the UI re-reads state through
the normal **FGA-governed** BFF path, so the stream can never disclose more than the caller may already
read, and a dropped/duplicated event only costs a redundant (or slightly late) re-read. The stream
endpoint itself is admin-gated and audited (a dedicated `event_stream_opened` audit event, same
two-layer pattern as credential vending / access review).

## Phased build

1. **P1 — emit + bus (backend-only, shippable alone).** `control_events.py` model + `control_emit.py` +
   the emit calls + chart topic/stream + `LANCE_CONTROL_EMIT_*` config. Unit tests assert each mutation
   publishes the right event with the verified actor; an integration test drains the topic. *Value even
   without the UI: internal consumers + a durable feed.*
2. **P2 — SSE endpoint.** `GET /v1/events/stream` with the per-connection consumer, admin gate, audit
   event, heartbeat, clean teardown. Test: open the stream, drive a grant, assert the frame arrives;
   assert non-admin → 403.
3. **P3 — frontend live-refresh.** BFF passthrough + shared `EventSource` client + per-zone
   `invalidate` wiring + the toast. Playwright: two contexts — mutate in one, assert the other's panel
   refreshes without a manual reload.

## Key decision (for review)

**Delivery mechanism = SSE (recommended) vs. short-polling.** SSE gives true live push and reuses the
bus; its one cost is the per-connection JetStream consumer + long-lived connection (fine on
adapter-bun, and the admin-gated audience is small). Short-polling (a `/v1/events?since=cursor` +
bounded ring buffer, frontend polls every ~5s) is simpler and needs no streaming, but is not "live" and
adds steady request load. **Recommendation: SSE**, because "propagated and refreshed in the frontend"
is explicitly the ask and the JetStream/BFF pieces already exist. Open sub-decision: **single-replica
in-memory fan-out (MVP)** vs. **per-connection JetStream consumer (multi-replica-correct)** — plan
above picks the latter; the MVP is the fallback if we want P2 faster with a documented caveat.

## Risks / caveats
- **Multi-replica SSE fan-out** is the one genuinely tricky part (why the per-connection JetStream
  consumer, not a Dapr competing subscription). If we accept the single-replica caveat short-term,
  document it next to `moverReplicas=1`.
- **Emit must be fail-open** — wrap every publish so a bus outage degrades to "no live refresh + audit
  still records it", never a failed mutation.
- **No new secrets / auth surface** — the SSE endpoint reuses OIDC+FGA and the Dapr app-token; the BFF
  reuses the existing session→bearer forwarding.

## Verification (end-to-end)
- `uv run pytest` — new unit tests for `control_emit` (each mutation → expected event, verified actor)
  and the SSE endpoint (admin 200 + frame delivery; non-admin 403).
- Integration: publish→drain the `catalog.control` topic; assert CloudEvent shape.
- Live (kind): drive a grant/revoke + a warehouse deactivate via the governed stack; assert the event
  on the bus and the console panel refreshing live (Playwright two-context test).
- `uvx ruff check .` · `uvx ty check` green.
