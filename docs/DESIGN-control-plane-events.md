# DESIGN — Control-plane change-events + live frontend refresh

> **Status: SHIPPED (2026-07-23) — P1 + P2 built, adversarially audited, and PROVEN live on kind**
> (`scripts/verify_control_events.sh`: mutation → `catalog.control.v1` broadcast → per-replica ring buffer →
> `GET /v1/events`, estate-admin gated, actor = the verified subject). Revised twice: a Fable-model plan
> review (2026-07-22) and a design/security review (2026-07-23) that corrected the estate-admin scope, the
> `APP_API_TOKEN` ingest auth, poll-audit volume, and the `query.live` frontend shape (see the review notes
> below + `docs/GOAL-finish-lance-ns.md`). Scope is **Lance-only**: an *internal* estate event stream for our
> own consumers + console, not foreign-catalog interop.

## Context

`BENCH-2026-07-22.md` concluded that after the week's shipping, the **only** in-scope catalog gap left
is **control-plane change-events**: today the catalog emits **data** events (OpenLineage over
Dapr/NATS, `core/lineage_emit.py`) describing table *writes*, but nothing emits **governance/metadata**
changes — *a grant changed*, *a warehouse was deactivated*, *a policy was set*, *a namespace/table was
created/dropped*. Those mutations happen and land in the **audit trail** (GreptimeDB, #41), but there is
no real-time **subscribable stream** and no way for the console to know without a manual reload.

Polaris 1.5 (multi-event-listener) and Lakekeeper (CloudEvents → NATS/Kafka) both ship this. The value
here is concrete: **the SvelteKit console refreshes itself** shortly after a grant/warehouse/policy
change (no stale access panels for an admin watching the estate), and internal consumers (cache
invalidation, an in-estate reaction worker) get a clean feed. The transport already exists — this is a
new topic + emit calls + a poll/stream endpoint, **not** a new broker client.

## Goals / non-goals

**Goals**
- Emit a typed **`CatalogControlEvent`** on every control-plane mutation, onto the existing Dapr/NATS bus.
- Surface those events in the browser so the affected console views **refresh (near-)live**.
- Reuse the existing emitter/transport/auth patterns — **no direct broker client in app code** (the
  `lineage_emit.py` principle; the catalog has no `nats-py` and must not grow one).
- **Fail-open on emit** — a mutation must never fail because eventing is down (mirror `lineage_emit`).

**Non-goals**
- Foreign-catalog interop / federation / Delta-Sharing (out of scope, Lance-only).
- Replacing the audit trail (that stays the durable compliance record; this is the live-notify layer).
- Guaranteed exactly-once browser delivery (the UI treats an event as a *refresh hint*, then re-reads
  authoritative state through the normal FGA-governed BFF path — see "Trust model").

## Architecture

Three seams: **emit** (catalog) → **bus** (Dapr/NATS, broadcast to every replica) → **console**
(poll first; SSE as a later upgrade).

```
mutation endpoint ──emit──▶ core/control_emit.py ──▶ Dapr pubsub.jetstream  topic: catalog.control
                                                                │  (subscriber WITHOUT queueGroupName
                                                                │   → every catalog replica gets every event)
   each replica: Dapr subscription ─▶ bounded in-memory ring buffer (monotonic cursor, event_id dedupe)
                                                                │
   browser ◀─poll every ~5s──  zone BFF  ◀── catalog GET /v1/events?since=<cursor>  (admin-gated)
```

### 1. Emit (catalog) — P1
- **New `services/catalog/core/control_emit.py`**, mirroring `core/lineage_emit.py`: a `ControlEmitter`
  with the same Dapr-vs-HTTP transport selection, built + torn down in the `main.py` lifespan on
  `app.state.control_emitter`, driven by `LANCE_CONTROL_EMIT_*` settings (default **off**, like lineage).
  Uses `services/common/dapr_publish.py::publish_event` — **no broker client**.
- **New event model `CatalogControlEvent`** (`services/common/control_events.py`, shared so consumers
  import it): `{ event_id, occurred_at, action, object_type, object_id, actor, extra }` wrapped as a
  CloudEvent (the envelope the lineage consumer already speaks). `action` enum:
  `grant_added | grant_revoked | warehouse_created | warehouse_activated | warehouse_deactivated |
  warehouse_bound | policy_set | policy_deleted | namespace_created | namespace_dropped |
  table_created | table_dropped | table_renamed | table_registered | table_deregistered | table_declared`.
- **Emit sites** — publish **after** the backend/FGA mutation succeeds, best-effort (verified `actor`
  from the OIDC token in scope, never self-asserted):
  | Endpoint (`services/catalog/api/v1/endpoints/…`) | action(s) |
  |---|---|
  | `access.py` grant / revoke | `grant_added` / `grant_revoked` |
  | `warehouses.py` create / activate / deactivate / bind | `warehouse_*` |
  | `policies.py` set / delete | `policy_set` / `policy_deleted` |
  | `namespaces.py` create / drop | `namespace_created` / `namespace_dropped` |
  | **`data.py`** `POST /{id}/create` | `table_created` *(create lives here, NOT tables.py)* |
  | `tables.py` drop / **rename** / register / deregister / declare | `table_dropped` / `table_renamed` / … |
  `table_renamed` matters most for the UI (it invalidates every open view of that table).

### 2. Bus + per-replica buffer (chart + catalog) — P1
- Add topic **`catalog.control`** to `chart/templates/dapr-component.yaml` and a **`CATALOG_CONTROL`**
  JetStream stream/subject to `chart/templates/nats-stream-job.yaml` (alongside LINEAGE/MEDALLION/TRAINING).
- **Broadcast, not competing-consumer:** the catalog registers a Dapr subscription on `catalog.control`
  **without `queueGroupName`**, so **every** catalog replica receives **every** event (the documented
  broadcast trick in `dapr-component.yaml`) — this is the multi-replica-correct fan-out with **zero new
  dependencies**, NOT a per-connection NATS consumer (the catalog has no NATS client and must not grow
  one). Each replica appends events to a **bounded in-memory ring buffer** with a monotonic cursor.

### 3. Console refresh — P2 (poll, the default) → P3 (SSE upgrade, later)

**P2 — short-poll (recommended default).**
- **Catalog `GET /v1/events?since=<cursor>`** (new, `endpoints/events.py`): returns ring-buffer events
  after `cursor` + the new head cursor; if `cursor` is older than the buffer's oldest retained event
  (overflow), returns a `reset: true` signal. **OIDC + FGA gated** by a real catalog-side
  `project:#can_administer` check (see "Auth note") — same admin bar as the `/audit` viewer.
- **Zone BFF `routes/events/+server.ts`** (data + admin zones): a plain proxy to `/v1/events`,
  attaching the session bearer exactly like the existing `capi/[...path]` proxy.
- **Frontend** (`frontend/packages/api/src`, shared): a small `pollControlEvents(onEvents)` that GETs
  every ~5s carrying the last cursor. On a relevant event it calls SvelteKit **`invalidate(dep)`** for
  the matching `depends()` key so only the affected `load` re-runs (a `grant_*`/`table_renamed` on the
  open table invalidates that table's panel; a `warehouse_*` invalidates the warehouses list). On a
  `reset` (or after a network gap) it calls **`invalidateAll()`**. A lightweight toast/`StatusBoard`
  line surfaces "access changed — refreshed". **Debounce** invalidations per dep key to coalesce bursts.
- **Why poll first:** the audience is a small **admin** set; polling is trivially multi-replica-correct,
  avoids the nginx `proxy_buffering` / Bun `idleTimeout` / adapter-streaming hazards entirely, and has
  the same trust model. "Refreshed within ~5s" is enough for governance changes.

**P3 — SSE upgrade (optional, later; gated on the zone deploy path).**
- Same broadcast subscription feeds an **in-process fan-out** to that replica's local SSE connections
  (`GET /v1/events/stream`, `text/event-stream`) — still no broker client. Requires resolving, and the
  plan must not proceed to P3 until these are settled:
  - **Deployment:** the chart today deploys only `apps/web` (`lance-lineage-web`); the **data/admin
    zones exist only behind the dev microfrontends proxy** — P3 has no verified prod path until the MFE
    migration lands their chart wiring.
  - **Streaming hazards:** nginx `proxy_buffering off`/`X-Accel-Buffering: no` end-to-end (the BFF
    `makeBackendProxy` in `frontend/packages/api/src/bff.ts` forwards only `content-type` today);
    heartbeat **≤5s** or a raised adapter `idleTimeout` (Bun default 10s would kill a 15s-heartbeat
    stream); terminal-on-403 in the client wrapper (no `EventSource` reconnect hammering).

### Auth note (correcting the first draft)
The `/audit` "project-admin" bar is currently enforced **in the BFF** (admin zone's
`routes/api/audit/+server.ts` bearer-forwards to the medallion produce door's `GET /authorize`), **not
in the catalog** — the catalog has **no** project-admin check today. This feature must add a real
catalog-side `project:#can_administer` FGA gate for `GET /v1/events*` (object id = the caller's
project), reusing the `fga_deps.py` helper shape. Client-side, the console gates the poll/subscribe on
an **admin flag** and treats a 403 as **terminal**. Honest limitation: live refresh is **admin-only**,
so the non-admin whose *own* access just changed does **not** get a live refresh — the benefit is for an
admin observing the estate, not self-notification.

### Trust model
An event is a **refresh hint**, not authoritative data: on receipt the UI re-reads state through the
normal **FGA-governed** BFF path, so the feed can never disclose more than the caller may already read,
and a dropped/duplicated/late event only costs a redundant (or slightly delayed) re-read. The endpoint
is admin-gated and audited (`event_stream_opened` audit event, same two-layer pattern as vending /
access review). Each event carries an `event_id` for client-side dedupe.

## Phased build
1. **P1 — emit + bus + per-replica buffer (backend-only, shippable alone).** `control_events.py` model
   + `control_emit.py` + emit calls at the corrected sites + chart topic/stream + the no-queueGroup
   broadcast subscription + ring buffer + `LANCE_CONTROL_EMIT_*` config. Unit tests: each mutation
   publishes the right event with the verified actor; the subscription appends to the buffer; an
   integration test drains the topic. *Value even without UI: internal consumers + a durable feed.*
2. **P2 — poll endpoint + console refresh (the default live layer).** `GET /v1/events?since=` with the
   catalog-side admin FGA gate + audit event + `reset` semantics; BFF proxy; shared poll client;
   per-zone `invalidate` wiring + toast; debounce. Test: admin 200 + delivery, non-admin 403 (terminal),
   overflow → `reset` → `invalidateAll`; Playwright two-context: mutate in one, assert the other's panel
   refreshes without a manual reload.
3. **P3 — SSE upgrade (optional).** In-process fan-out stream, **only after** the zone prod deploy path
   and the streaming-hazard checklist above are resolved. If deferred, document it next to the other
   deferrals.

## Risks / caveats
- **No new broker client** — both poll and the SSE upgrade ride the Dapr subscription; do not add
  `nats-py`.
- **Emit must be fail-open** — wrap every publish so a bus outage degrades to "no live refresh + audit
  still records it", never a failed mutation.
- **Ring buffer is per-replica + in-memory** — bounded (drop-oldest); a client whose cursor fell off the
  end gets `reset`. Acceptable because events are hints and the buffer only needs to cover a poll gap.
  **Multi-replica boundary:** the buffer AND its monotonic cursor are per-replica, so at
  `services.catalog.replicas > 1` a load-balanced poll can hit different replicas and see inconsistent
  cursors → noisy (but safe) `reset`s. Correct at the default `replicas: 1`; scaling the catalog needs
  session affinity (client polls stick to one replica) or a shared buffer. The `query.live` generator
  cushions it (dedup by `event_id`, clear-on-`reset`), so it degrades noisily, never wrongly.
- **P3 is genuinely blocked** on the MFE migration (zone deploy) + the streaming hazards — do not start
  it until those clear.

## Verification (end-to-end)
- `uv run pytest` — unit tests for `control_emit` (each corrected mutation → expected event, verified
  actor), the broadcast subscription (buffer append), and the poll endpoint (admin 200 + delivery,
  non-admin 403, overflow `reset`).
- Integration: publish→drain `catalog.control`; assert CloudEvent shape; assert two replicas both
  buffer the same event (no queueGroup).
- Live (kind): drive a grant/revoke + a warehouse deactivate on the governed stack; assert the event on
  the bus and the admin console panel refreshing within the poll interval (Playwright two-context test).
- `uvx ruff check .` · `uvx ty check` green.

---

## Review (Fable-model pass, 2026-07-22)

Verdict: **P1 sound and buildable as-is; the original P2/P3 SSE design was not.** Revisions applied
from the review:
- **Transport corrected** — dropped the "per-connection JetStream ephemeral consumer" (the catalog has
  no NATS client; Dapr subscriptions are app-level/startup-registered). Now: Dapr subscription
  **without `queueGroupName`** → broadcast to every replica → per-replica ring buffer. No new deps.
- **Poll made the P2 default**, SSE demoted to an optional P3 upgrade — right call for a small admin
  audience; sidesteps the nginx-buffering / Bun-idle-timeout / adapter-streaming / zone-deploy hazards.
- **Admin gate fixed** — added the missing **catalog-side** `project:#can_administer` check (the
  `/audit` bar lives in the BFF today, not the catalog), client gates on an admin flag and treats 403 as
  terminal, and the admin-only limitation is stated honestly.
- **Emit sites corrected** — table `create` is in `data.py` (not `tables.py`); added `table_renamed`
  (+ register/deregister/declare) to the enum.
- **Added** reconnect-resync (`cursor` + `reset` → `invalidateAll`), backpressure (bounded buffer,
  drop-oldest), idempotency (`event_id`), and invalidate debounce.
- **Flagged** that P3 has no production deployment path until the data/admin zones are charted (MFE
  migration), so P3 is explicitly gated.
