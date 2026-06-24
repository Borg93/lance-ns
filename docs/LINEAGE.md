# Lineage service — OpenLineage → Apache AGE

The **provenance axis** from [`ARCHITECTURE.md`](ARCHITECTURE.md) §9. A *separate*
microservice (`lineage/`) that ingests OpenLineage events emitted by compute/ETL jobs and
answers "where did this data come from / where does it flow / who produced it" over a
graph. It is **not** part of the catalog control plane.

Think of it as a **lightweight Marquez** (the OpenLineage reference server): same OpenLineage
ingest contract, but a few hundred lines of FastAPI over a native graph store instead of a
Dropwizard service over a relational schema — and wired to *our* flow (dataset names are
catalog table ids, authors are OIDC subs).

## Why a separate service (not "SSR only")

Two hard constraints force a small backend rather than querying a DB from the UI:

1. **Ingestion is server-side.** OpenLineage events come from compute jobs (ray /
   promotion jobs), not the browser — something must receive them and write the graph.
2. **DB-per-service.** The AGE graph is owned by exactly one service; the frontend (SSR
   or otherwise) calls this service through the gateway, it never touches AGE directly.

So the lineage service owns **both** the write path (ingest) and the read path (query).
SSR is a rendering layer on top, not a substitute.

```
compute/ETL jobs ─POST /api/v1/lineage─▶ lineage svc ──owns──▶ Apache AGE (Postgres)
   (openlineage-python emitter)          │  ingest: event → MERGE Run/Job/Dataset + edges
   SSR UI ◀─via gateway─ GET upstream/downstream/producers/graph ◀┘  query: openCypher
```

## How it complements OpenFGA and Lance

| Question | System |
|---|---|
| **who** may read/write/commit | OpenFGA (`can_*` on `table:<id>`) |
| **what / when** changed | Lance versions + tags (immutable, time-travel) |
| **how / from where / by whom** | **this service** (OpenLineage graph) |

The dataset node's `name` **is** the catalog table id (e.g. `bronze$images`), so the same
object is governed by OpenFGA, versioned by Lance, and traced here — one identity across all
three axes. Read-side authz — gating lineage views by `can_get_metadata` on `table:<id>`
via the shared OpenFGA store — is now **implemented** (see the next section).

## Read-side authz (implemented — in-service, default OFF)

> ✅ **Implemented** (audit `w8u4rc2tg` P0; reviewed by `wi2l437mq`). The query + ingest
> endpoints are gated in-service (`lineage/auth.py`), **default OFF** like the catalog — set
> `LINEAGE_OIDC_ENABLED` + `LINEAGE_FGA_ENABLED` (+ the shared `LINEAGE_FGA_STORE_ID` /
> `LINEAGE_FGA_MODEL_ID`) in production. Ingest also requires a verified token and binds the run
> author to it (no forged provenance), and related/graph datasets the caller can't see are
> filtered out (`DatasetFilter`, via `fga.batch_check`).

The gate is two layers — the same the catalog applies to `describe table`:

1. **OIDC (who are you?)** — require a valid Bearer JWT verified against the IdP (Dex); no /
   invalid token → **401**.
2. **OpenFGA (may you see it?)** — check `can_get_metadata` on `table:<id>` before returning
   lineage; denied → **403**.

**Principle:** you may see a dataset's lineage only if you may see that table's metadata — the
*same* `can_get_metadata` permission, so policy lives in one place (the OpenFGA model) and is
never duplicated here. It matters because lineage leaks the data estate: `upstream` /
`downstream` reveal which datasets exist and how they connect, and `producers` reveals who ran
which jobs.

**What it does and does not couple.** It does **not** couple lineage to the catalog — the two
services still never call each other; their only link is the shared `table:<id>` identity
convention. It makes lineage a **client of the shared auth plane** (the same OpenFGA store +
the same IdP). "Reusing the catalog's store" means lineage only **reads** the tuples the
catalog **already wrote** on table creation — it never seeds or writes tuples, so OpenFGA
stays the single source of truth for who-can.

**Alternative — gateway gating.** Keep lineage dependency-free and enforce `can_get_metadata`
at the gateway / SSR layer instead; lineage stays open behind it. Weaker boundary (lineage
trusts the gateway) but zero OpenFGA/OIDC dependency in the service. **Decision: in-service**
(implemented above) — the lineage service owns the audit graph, so it enforces its own
boundary rather than trusting a gateway.

## Relation to Marquez (what we kept, what we made lighter)

| | Marquez (reference) | This service |
|---|---|---|
| Ingest | `POST /api/v1/lineage` | **same path** — any OpenLineage producer is drop-in |
| Backend | Dropwizard (Java, large) | FastAPI, ~6 files |
| Store | relational Postgres + Flyway migrations; lineage computed via recursive SQL | **Apache AGE graph** — upstream/downstream is one `*1..` Cypher |
| Identity | `(namespace, name)` | catalog table id (shared with OpenFGA + Lance) |
| UI | bundled React app | deferred; the `/graph` endpoint feeds a future SSR micro-frontend |

We deliberately store lineage as a **graph** (it *is* one) rather than reconstructing it from
relational tables, and we drop everything not needed for the medallion flow.

## Graph model (Apache AGE)

```
(:Job {namespace, name})
(:Run {run_id, author, event_type, event_time})
(:Dataset {name, namespace})          # name = catalog table id; MERGEd on name only
(:User {name})                        # an OIDC sub (the verified principal)
(:Run)-[:OF_JOB]->(:Job)
(:Run)-[:READ]->(:Dataset)            # inputs
(:Run)-[:WROTE]->(:Dataset)           # outputs
(:Dataset)-[:DERIVED_FROM]->(:Dataset)# output ← input (dataset-level lineage)
(:User)-[:CREATED]->(:Dataset)        # who created the table (catalog create event)
```

`author` is read from a custom OpenLineage `author` run facet (the OIDC sub of whoever ran
the job). On a catalog **create** event (`lance` facet `operation=create_table`, emitted by
`app.core.lineage_emit`), the verified author is also recorded as a first-class
`(:User)-[:CREATED]->(:Dataset)` edge — the authoritative "who created this table" answer.
Datasets are MERGEd on `{name}` only, then `namespace` is `SET`, so a dataset referenced by
several runs is never duplicated.

## Code shape (FastAPI house style)

Layered, no raw Cypher in the endpoints:

- `lineage/models.py` — Pydantic `RunEvent` (the OpenLineage wire subset we ingest; camelCase aliases).
- `lineage/schemas.py` — typed response models (`Neighbors`, `Producers`, `LineageGraph`).
- `lineage/age.py` — thin Apache AGE client over `psycopg`; safe SQL via `psycopg.sql` composition.
- `lineage/repository.py` — `LineageRepository` (the only place Cypher lives) returning the schemas above.
- `lineage/main.py` — FastAPI app; lifespan builds the pool + repository onto `app.state`, injected via an `Annotated` dep; every route has a typed `response_model`.
- `lineage/seed.py` — **producer-side** OpenLineage emitter (see below); the service never imports it.

## API

| Method / path | Purpose |
|---|---|
| `POST /api/v1/lineage` | Ingest one OpenLineage `RunEvent` (OpenLineage HTTP-transport default path) |
| `GET /datasets/{name}/upstream` | What `name` was derived from (provenance) |
| `GET /datasets/{name}/downstream` | What derives from `name` (impact) |
| `GET /datasets/{name}/producers` | The runs that wrote `name` — who / when / how |
| `GET /datasets/{name}/creator` | **Who created** `name` (the verified catalog principal) |
| `GET /datasets/{name}/graph` | Connected lineage subgraph (`nodes` + `edges`) for a DAG view |
| `GET /livez` | Liveness |

`name` is the catalog table id, e.g. `bronze$images`. Because the ingest path is the
OpenLineage default, any OpenLineage-instrumented producer (our emitter, Airflow, Spark, dbt)
pointed here with `OPENLINEAGE_URL` ingests with no glue.

> ✅ The query + ingest endpoints are **gated in-service** (default OFF; enable in prod) — see
> [Read-side authz](#read-side-authz-implemented--in-service-default-off).

## Mock medallion data (a real OpenLineage producer)

`lineage/seed.py` is the **producer** — compute-layer instrumentation that uses the official
`openlineage-python` client to build spec-correct events for the medallion flow (faithful to
`ARCHITECTURE.md` §6: dataset names = catalog ids, authors = OIDC subs, bronze carries a
schema facet `{image, img_src}`):

```
ingest_images          (alice)    raw_images          → bronze$images {image, img_src}
lanceray_append_images (alice)    raw_images_batch2   → bronze$images          (append)
lanceray_embed         (data_eng) bronze$images       → silver$features {…, embedding}
aggregate_gold         (analyst)  silver$features     → gold$catalog
```

`lineage/sample_events.json` is generated from it (`--write`), so the static fixture stays in
sync with what a real OpenLineage client emits. After ingest: `upstream(gold$catalog)` →
silver, bronze, both raw sources; `producers(silver$features)` → the `data_eng` lance-ray run.

## Run / verify (dev)

```bash
# Apache AGE Postgres (the lineage graph store)
docker compose -f .docker/docker-compose.yml -f .docker/docker-compose.lineage.yml up -d lineage-postgres

# the service
LINEAGE_DATABASE_URL=postgresql://lineage:lineage@localhost:5433/lineage \
  uv run uvicorn lineage.main:app --port 2334

# seed the mock medallion history via the OpenLineage emitter, then query
uv run python -m lineage.seed --emit http://localhost:2334
curl -s localhost:2334/datasets/gold\$catalog/upstream | jq
curl -s localhost:2334/datasets/silver\$features/graph | jq

# regenerate the static fixture from the emitter (instead of emitting)
uv run python -m lineage.seed --write lineage/sample_events.json

# tests
uv run pytest tests/unit/test_lineage.py -q                                   # our logic, no DB
LINEAGE_DATABASE_URL=postgresql://lineage:lineage@localhost:5433/lineage \
  uv run pytest tests/e2e/test_lineage_e2e.py -q                              # ingest + query vs live AGE
```

> pylance has no macOS wheel, so the lockfile is Linux-only — run the tests in the
> `ghcr.io/astral-sh/uv:python3.13-trixie-slim` container (joined to the compose network),
> as the catalog tests already are.

## Next

- ✅ **Read-side authz** — done (in-service OIDC + OpenFGA `can_get_metadata`, ingest author
  binding, transitive-disclosure filtering). Default OFF; enable in prod. See **Read-side authz** above.
- **Output-scoped ingest authz** — additionally check the producer may write the named output
  tables (`can_write_data`), not just that it is authenticated. Attributable today, not yet scoped.
- ✅ **Deployed** — `lineage-api` service (`.docker/docker-compose.governance.yml`, same image) +
  `COPY lineage/` in the dockerfile. Catalog emits create-lineage to it (`/datasets/{id}/creator`).
- **Async ingest at scale:** jobs publish OpenLineage to NATS; the service consumes
  (same owner, just decoupled). Direct `POST /api/v1/lineage` is fine until then.
- **Frontend:** an SSR micro-frontend renders the DAG by calling `/graph` via the gateway
  (no direct DB access).
- **Verify the whole loop:** `scripts/governance_e2e.sh` (or `DEMO=1 …` for the narrated
  `scripts/governance_demo.py`) — authz + create-lineage + medallion provenance over the full stack.
