# lance-ns — how it all works (event-driven on kind)

A Lance lakehouse REST catalog + in-service lineage (OpenLineage → Apache AGE) + governance, running as
**event-driven microservices on a local kind cluster**, deployed by one umbrella Helm chart and
iterated with Tilt. Diagram: [`k8s-event-driven-architecture.html`](k8s-event-driven-architecture.html).

## One command

```bash
make up        # bootstrap toolchain + kind cluster + build images + deploy everything
make verify    # prove the event-driven flow end-to-end
make dashboards# port-forward the UIs (web / lineage / Perses / GreptimeDB / Dapr dashboard)
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
| **medallion** | 4 apps + sidecars | event-driven pipeline: `lance-ray` producer + raw→bronze→silver→gold movers (see [MEDALLION.md](MEDALLION.md)) |
| **compaction** | app + sidecar | compaction/GC service triggered by a Dapr **cron binding** (`bindings.cron`) — compacts Lance fragments + GCs old versions |
| **gateway** | nginx + sidecar | single entry point — clean-URL edge that routes app traffic via **Dapr service invocation** (`/v1.0/invoke/...`); `/`→web, `/lineage/`,`/catalog/`,`/produce` (values-gated: `medallion.producer.expose`, off in prod — it's the unauthenticated demo entry),`/perses/`,`/greptime/`. Dapr-delivered routes (lineage ingest + the reconcile cron binding) are **403-blocked** from one source (`lance.lineageSidecarOnlyRoutes`) — the sidecar is their only legitimate caller |
| **Dapr** | subchart | control plane + sidecar injection + pub/sub + secret-store + tracing config |
| **NATS** | subchart | JetStream — the durable event bus behind Dapr pub/sub |
| **Apache AGE Postgres** | StatefulSet | the lineage graph (`lineage`) **and** OpenFGA's datastore (`openfga` db) |
| **OpenFGA** | subchart | Zanzibar authz (datastore = the AGE Postgres) |
| **Dex** | Deployment | OIDC issuer (authn) |
| **RustFS** | Deployment | S3-compatible object store for the Lance lakehouse |
| **OpenBao** | Deployment | secret store (Vault fork), fronted by a Dapr `secretstores.hashicorp.vault` component |
| **GreptimeDB** | subchart | **one unified store for metrics + logs + traces** (on RustFS S3) — apps export OTLP-direct here |
| **Vector** | subchart | Agent DaemonSet shipping pod logs → GreptimeDB (`lance_logs`) |
| **Perses** | subchart | dashboards-as-code over GreptimeDB's Prometheus API (`/v1/prometheus`) |
| **Dapr dashboard** | Deployment | web UI for the Dapr stuff (components, subscriptions, configurations) |

## The event-driven path (verified)

```
catalog --DaprClient.publish_event--> [daprd sidecar] --pubsub.jetstream--> NATS JetStream (stream LINEAGE)
                                                                                   │
   Apache AGE  <--cypher-- lineage  <--POST /lineage-events-- [daprd sidecar] <-----┘
   (:User)-[:CREATED]->(:Dataset)        (Dapr subscription)
```

- The catalog publishes to its **local** sidecar; the sidecar owns retry/backoff + **W3C
  trace-context propagation** as component config (no broker client in app code; no DLQ —
  [`RESILIENCE.md`](RESILIENCE.md) gap #2).
- The lineage service subscribes via `dapr-ext-fastapi` (`/dapr/subscribe` → `/lineage-events`),
  ingests into AGE, and returns the Dapr ack status (`SUCCESS`/`RETRY`/`DROP`). Ingest is idempotent
  (MERGE on `run_id`).
- **Every subscriber has its own pubsub component** (`lineage-pubsub-<app-id>`, the `lance.subPubsub`
  helper): `queueGroupName=<app-id>` makes that app's replicas a competing-consumer group (single
  delivery per app — safe to scale), and `deliverPolicy` is `all` for lineage (restart replays into the
  idempotent MERGE = the durability story) but `new` for the cascade head + movers (a replay would
  re-fire every cascade in the 168h retention window). The bare `lineage-pubsub` component is publish-only
  (catalog + compaction).
- `make verify` publishes a `create_table` event and asserts AGE recorded the creator.

## Observability (GreptimeDB + Vector + Perses — the rask stack)

All three OTel signals are **valuable and queryable**, mirroring rask: the apps run under
`opentelemetry-instrument` and export **OTLP-direct to GreptimeDB** (`:4000/v1/otlp`, `http/protobuf`,
`x-greptime-*` headers) — **no OTel Collector** in the path. GreptimeDB is one unified store; Perses
dashboards it over GreptimeDB's Prometheus-compatible API. Verified end-to-end (`make e2e-obs`):

- **Traces** → `opentelemetry_traces`. A **single distributed trace spans catalog → Dapr publish →
  lineage → AGE write** (`opentelemetry-instrumentation-grpc` injects `traceparent` into the gRPC
  publish; the lineage FastAPI extracts it). Dapr's `lance-tracing` Configuration keeps `samplingRate=1`
  so the W3C context always propagates — it has **no** otel exporter (Dapr's own spans can't carry
  GreptimeDB's required headers; the apps do all export).
- **Metrics** → PromQL. Custom **domain** golden signals `lineage_events_processed_total{lance_lineage_outcome}` +
  `lineage_ingest_duration_seconds_*` (recorded in the consumer), plus FastAPI RED
  (`http_server_duration_milliseconds_*`). Export interval is 5s (`OTEL_METRIC_EXPORT_INTERVAL`).
- **Logs** → app OTLP logs (`opentelemetry_logs`) **and** Vector pod logs (`lance_logs`).

`make e2e-obs` runs `tests/e2e/test_observability_e2e.py` — one catalog table-create, then it asserts the
graph data landed in AGE, the metric incremented in PromQL, the distributed trace joined catalog+lineage,
and both log tables are populated. That's the regression guard for "the pipeline works **and** is observable".

**Lance-native IO metrics (pre-wired, activates at pylance 9):** pylance ≥ 9.0 ships
`lance.otel.instrument_lance_metrics()` (the `pylance[otel]` extra) — Lance's Rust object-store/IO
metrics registered straight onto the global MeterProvider the services already run under. Every
Lance-I/O service (catalog, lineage, compaction, medallion producer + movers) already calls the guarded
`common.lance_metrics.instrument_lance_if_available()` at startup; at the pinned pylance 8.0.0 it logs
`lance_metrics_unavailable` and no-ops. When 9.0 ships on PyPI (8.0.0 is the newest as of 2026-07-10),
switch the pin to `pylance[otel]` (marked in `pyproject.toml`) and the metrics appear in GreptimeDB with
no further code. OTel has no async histogram instrument, so Lance histograms arrive Prometheus-style as
`<name>_bucket`/`_count`/`_sum` counters with `le` attributes.

## Governance (Dex + OpenFGA)

Deployed; `auth.enabled=false` by default. Set `auth.enabled=true` to wire OIDC (Dex) verification +
OpenFGA `can_get_metadata` checks into the catalog + lineage. The OIDC `ALLOW_INSECURE` escape hatch is
SCHEME-DERIVED from the issuer (2026-07-12): a plain-http issuer (the in-cluster dev Dex) opens it, an
https issuer (any real IdP) keeps the verifier's HTTPS guard enforced — never hardcoded open. OpenFGA's schema migrates against the AGE
Postgres (pinned to v1.8.0; the openfga db's `search_path` is forced off AGE's `ag_catalog`).

## Notable engineering notes

- **Dapr JetStream consumers** are split BY RECOVERY STORY (2026-07-06/12): the LINEAGE ingest stays
  **ephemeral** (deliverPolicy=all — a restart replays the retained stream into the idempotent MERGE;
  a durable cursor would defeat that recovery), while the cascade head + movers pair
  `deliverPolicy=new` with a **durable + queue-group** consumer (cursor survives pod death/redeploys —
  chaos-verified; the durable-orphan failure applies only to durables WITHOUT a queue group). Since
  2026-07-12 the **Dapr Resiliency + DLQ layer is DEFAULT ON** (`dapr.resiliency.enabled`): the sidecar
  owns delivery retries (30s→300s ×5) and exhaustion PARKS the message on the per-app `dlq.*` topic
  (own DLQ stream) — see docs/RESILIENCE.md gap #2. The durable PULL consumer move remains the last
  hardening follow-up.
- **AGE + OpenFGA share one Postgres**: AGE's `ag_catalog` search-path would break OpenFGA migrations,
  so the openfga db is pinned to `search_path = public` in the AGE initdb.
- **kind has no host ports** — reach services via `make dashboards` (port-forwards).

## Status (audited)

✅ Verified: the event-driven catalog→lineage flow, all components healthy (`helm STATUS: deployed`),
Dapr sidecar injection, the full 3-signal observability (`make e2e-obs` green — AGE data + PromQL metric
+ distributed trace + logs in GreptimeDB), `tilt ci` brings the whole stack up green.
✅ Verified: the event-driven **medallion** cascade — one `lance-ray` `/produce` cascades
raw→bronze→silver→gold via Dapr pub/sub, building the lineage DAG, as **one distributed trace** across
all 5 services, with the `medallion_stage_transitions_total` metric in PromQL (`make e2e-medallion`).
✅ Verified: the **compaction/GC** service — a Dapr `bindings.cron` component POSTs `/compaction-cron`
on its schedule (and `make compaction` on demand); each sweep discovers every Lance dataset in the bucket
and runs `compact_files()` + `cleanup_old_versions()`, with `compaction_*` metrics in PromQL.
✅ Verified: the **API gateway** — one nginx front routes `/lineage/*` and `/catalog/*` through its own
Dapr sidecar via **service invocation** (mTLS + retries + tracing on the hop), `/`→web UI; one
port-forward fronts the whole platform (`/lineage/livez` → 200 through the gateway).
✅ Verified: **OpenBao secret consumption** — apps read secrets through their Dapr sidecar
(`GET /v1.0/secrets/lance-secrets/lance` → 200) instead of plaintext env. Fixed the kv-v2 nuance:
Dapr defaults `vaultKVPrefix=dapr` (reads `secret/data/dapr/<key>`); set `vaultKVUsePrefix=false` so it
reads the natural `secret/data/<key>` the seed writes.
✅ Verified: the **Lakekeeper-style multi-tenant ReBAC** — `team → project → warehouse(bucket) →
namespace → table` with concentric `owner>writer>reader` rungs + a `validator` rung that gates medallion
stage promotion. Proven offline (`fga model test`: 7/7 tests, 24/24 checks) **and** live against the
deployed OpenFGA: a plain writer `can_promote` gold = **false**, a validator = **true**; projects are
isolated (one bucket per project; a team can own many). See `services/common/auth/model.fga` + `model.fga.yaml`.
⚠️ Deployed-not-wired: the app auto-seeding of the project/team/warehouse hierarchy on create (the
namespace→warehouse parent + creator-owner are seeded; project/team/validator grants are set out-of-band
for now); the end-to-end Dex-token → catalog → OpenFGA request demo (auth is `--set auth.enabled=true`).
✅ Built: RustFS-native scoped STS via `vending.mode=web_identity` (Dex id_token →
`AssumeRoleWithWebIdentity` + inline per-table session policy). Plain `AssumeRole` STS (`vending.mode=sts`)
works on AWS/MinIO/Ceph but NOT RustFS (it rejects plain AssumeRole — that's why web_identity exists).
