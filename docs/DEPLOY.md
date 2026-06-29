# lance-ns — how it all works (event-driven on kind)

A Lance lakehouse REST catalog + in-service lineage (OpenLineage → Apache AGE) + governance, running as
**event-driven microservices on a local kind cluster**, deployed by one umbrella Helm chart and
iterated with Tilt. Diagram: [`k8s-event-driven-architecture.html`](k8s-event-driven-architecture.html).

## One command

```bash
make up        # bootstrap toolchain + kind cluster + build images + deploy everything
make verify    # prove the event-driven flow end-to-end
make dashboards# port-forward the UIs (web / lineage / Jaeger / Dapr dashboard)
make k9s       # inspect the cluster
make tilt-up   # dev loop: hot-reload the FastAPI services
make down      # tear down
```

`make up` is idempotent. It needs only **docker** + **helm** on PATH; it downloads kind/kubectl/k9s/tilt
into `.localbin/` (gitignored).

## The components (one `helm install`, all gated by `<key>.enabled`)

| Component | Kind | Role |
| --------- | ---- | ---- |
| **catalog** | app (FastAPI) + daprd sidecar | **producer** — creates Lance tables on S3; publishes OpenLineage events via Dapr |
| **lineage** | app (FastAPI) + daprd sidecar | **consumer** — Dapr subscription ingests events into Apache AGE; serves the lineage API |
| **web** | app (SvelteKit) | the UI (datasets / jobs / columns DAG) |
| **Dapr** | subchart | control plane + sidecar injection + pub/sub + secret-store + tracing config |
| **NATS** | subchart | JetStream — the durable event bus behind Dapr pub/sub |
| **Apache AGE Postgres** | StatefulSet | the lineage graph (`lineage`) **and** OpenFGA's datastore (`openfga` db) |
| **OpenFGA** | subchart | Zanzibar authz (datastore = the AGE Postgres) |
| **Dex** | Deployment | OIDC issuer (authn) |
| **RustFS** | Deployment | S3-compatible object store for the Lance lakehouse |
| **OpenBao** | Deployment | secret store (Vault fork), fronted by a Dapr `secretstores.hashicorp.vault` component |
| **Jaeger** | Deployment | tracing backend + UI — Dapr sidecars export spans here (OTLP) |
| **Dapr dashboard** | Deployment | web UI for the Dapr stuff (components, subscriptions, configurations) |

## The event-driven path (verified)

```
catalog --DaprClient.publish_event--> [daprd sidecar] --pubsub.jetstream--> NATS JetStream (stream LINEAGE)
                                                                                   │
   Apache AGE  <--cypher-- lineage  <--POST /lineage-events-- [daprd sidecar] <-----┘
   (:User)-[:CREATED]->(:Dataset)        (Dapr subscription)
```

- The catalog publishes to its **local** sidecar; the sidecar owns retry/backoff/DLQ + **W3C
  trace-context propagation** as component config (no broker client in app code).
- The lineage service subscribes via `dapr-ext-fastapi` (`/dapr/subscribe` → `/lineage-events`),
  ingests into AGE, and returns the Dapr ack status (`SUCCESS`/`RETRY`/`DROP`). Ingest is idempotent
  (MERGE on `run_id`).
- `make verify` publishes a `create_table` event and asserts AGE recorded the creator.

## Observability (OTel for Dapr)

A Dapr `Configuration` (`lance-tracing`) makes the catalog + lineage sidecars export **distributed
traces** over OTLP to **Jaeger** — no app code needed. The `/v1.0/publish/lineage-pubsub/...` span and
the lineage delivery span show up in the Jaeger UI. (App-level OTel SDK metrics/logs, and a standalone
OTel Collector fan-out, are the next layer.)

## Governance (Dex + OpenFGA)

Deployed; `auth.enabled=false` by default. Set `auth.enabled=true` to wire OIDC (Dex) verification +
OpenFGA `can_get_metadata` checks into the catalog + lineage. OpenFGA's schema migrates against the AGE
Postgres (pinned to v1.8.0; the openfga db's `search_path` is forced off AGE's `ag_catalog`).

## Notable engineering notes

- **Dapr JetStream consumer** uses an **ephemeral** consumer (no `durableName`): a durable PUSH
  consumer orphans on every pod redeploy ("consumer name already in use") and silently halts ingestion.
  Ephemeral is auto-cleaned + recreated cleanly; idempotent ingest makes any replay a no-op. Durable
  redelivery across a redeploy gap (a durable PULL consumer) is the production-hardening follow-up.
- **AGE + OpenFGA share one Postgres**: AGE's `ag_catalog` search-path would break OpenFGA migrations,
  so the openfga db is pinned to `search_path = public` in the AGE initdb.
- **kind has no host ports** — reach services via `make dashboards` (port-forwards).

## Status (audited)

✅ Verified: the event-driven catalog→lineage flow, all components healthy (`helm STATUS: deployed`),
Dapr sidecar injection, Jaeger traces, `tilt ci` brings the whole stack up green.
⚠️ Deployed-not-wired: auth (`auth.enabled=false`); OpenBao secret read via Dapr (kv-v2 path nuance).
❌ Not built: the medallion stage movers (raw→bronze / bronze→silver / silver→gold) as event-driven
services + a dummy Ray producer; a compaction/GC microservice; an API gateway; RustFS STS.
