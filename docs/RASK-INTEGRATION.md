# Merging the lakehouse into rask — integration checklist

This repo's deliverable is **contributed into the sibling `rask/` repo**, not shipped standalone. This is the
concrete migration plan: what folds in, what externalizes to rask's operators, the lance-ray seam contract,
and what to drop. Grounded in rask's actual chart (`rask/chart/`) + this repo's services + chart.

## The boundary (what moves vs what rask supplies)

**We bring (the unit that merges):**
- The **lakehouse catalog** (`services/catalog`, a thin REST adapter over native pylance `DirectoryNamespace`) + the in-process `dataplane`.
- The **lineage estate** (`services/lineage` → Apache AGE graph; OpenLineage; `/reconcile`; column-level + the gold whole-history JSONB). **rask has ZERO lineage** — this is the single biggest net-new capability we add.
- The **OpenFGA WIRING** (`services/common/auth/model.fga` + `services/catalog/api/fga_deps.py` + credential vending). **rask provisions OpenFGA but never wires it into any service** — we bring the actual ReBAC enforcement.
- The **event-driven medallion estate** (`services/medallion` producer + movers, `services/compaction`) on Dapr pub/sub over NATS JetStream.

**rask supplies (use, do NOT rebuild):**
- **CloudNativePG** — the Postgres `Cluster` (`<release>-postgres`).
- **rustfs-operator** — the S3 `Tenant` (`<release>-rustfs`, with a `buckets:` list).
- **KubeRay + Kueue** — the Ray cluster (`RayService`) + job admission, and the `ray-kit` / orchestrator submission path.
- **Frontends** (SvelteKit microfrontends) + **Traefik Ingress** + the **Alembic migration Job** + **GreptimeDB/Vector/Perses** observability + **NATS** + **Dapr**.

## Pre-flight (rask already has these — no action)
NATS, Dapr, OpenFGA (server), CloudNativePG, rustfs-operator, KubeRay, Kueue, GreptimeDB stack, Traefik. The
chart pattern is identical (umbrella + `*.enabled` subcharts + externalize-in-prod), so the fold-in is values
+ templates, not a new paradigm. Which of these operators we lean on first, in what order, and why no custom
lance-ns operator is ever built: [`OPERATORS.md`](OPERATORS.md) (also pins the submit-seam boundary — the
agnostic Jobs-REST seam stays in lance-ns; rask supplies the `RayJob`-CR transport behind the same
function signatures).

## Migration checklist

### 1. Stateful stores → rask's operators (via the P1 externalization hooks)
The externalization hooks added in this repo make this a **values flip**, not a code change:

| lance-ns value | Set to | Points at rask's |
|---|---|---|
| `rustfs.enabled` | `false` | — (drop the hand-rolled Deployment) |
| `rustfs.externalEndpoint` | `http://<release>-rustfs:<port>` | rustfs-operator `Tenant` |
| `age.enabled` | `false` | — (drop the hand-rolled StatefulSet) |
| `age.externalHost` | `<release>-postgres-rw` | CNPG `Cluster` (rw service) |
| `openfga.datastore.uri` | `postgres://…@<release>-postgres-rw:5432/openfga…` | CNPG |
| `observability.externalOtlpEndpoint` | rask's GreptimeDB OTLP | shared observability |

- **Add the buckets** to rask's `rustfs.buckets`: the lakehouse (`lance-catalog`) + observability (`lance-observability`).
- **Add the databases** to CNPG: `lineage` + `openfga`. ⚠️ **AGE caveat** — the lineage graph needs the Apache **AGE extension**; CNPG runs stock Postgres, so either (a) point CNPG at a **custom Postgres image with AGE**, (b) keep AGE as a separate operand, or (c) execute the `docs/DECISIONS.md` AGE-on-CNPG decision to move lineage to a **Lance-native graph** (drops the AGE/Postgres dependency entirely). Decide before the fold-in.

### 2. lance-ray → a real Ray Data job (the one in-scope gap)
Today `services/medallion/producer.py` + the movers are **dummy Ray jobs** — pure lineage emitters by
default, but with `medallion.compute=true` (the B1 toggle) each stage does a real in-process Lance
read→transform→write, so the cascade already produces versioned data, not just provenance. On rask
they become **real Ray Data jobs on KubeRay** (Kueue-admitted, `ray-kit`/orchestrator-submitted). The seam
contract they must honor (so they drop in with no rewiring) — see **§ lance-ray seam contract** below.

### 3. Wire OpenFGA into rask
rask provisions OpenFGA but doesn't enforce it. Contribute `model.fga` + `fga_deps` so rask's services check
ReBAC (and so the medallion `can_promote`/`can_create_table` gates fire). This also gives rask its first authz.

### 4. Secrets — align the two-tier model
Map this repo's OpenBao + external-secrets two-tier model onto rask's secret approach (rask uses
`existingSecret` for prod). Keep: app tier consumes via Dapr secret store (sole source); infra tier via
`secretKeyRef` populated by external-secrets from Vault. lance-ray uses **workload identity** (no durable
secret).

### 5. Drop the demo scaffolding (rask supersedes it)
- `chart/templates/{age-postgres,rustfs,backup-pg,backup-snapshot}.yaml` → CNPG / rustfs-operator.
- `frontend/` + the zone Deployments + `gateway.yaml` → rask's SvelteKit frontends + Traefik Ingress.
  **Grafted-shape (P5, 2026-07-22):** `frontend/` is now a Turborepo + bun workspace in rask's exact shape —
  the 4 `components/frontends/<zone>` apps (home/lakehouse/media/annotator) on the shared `@repo/ui` design
  system + the `@repo/api` seam (the old single `apps/web` app + `@repo/ui` were retired in P5) — so folding
  in is a directory graft of the zones into `rask/components/frontends/`, not untangling a monolith.
- `openbao` dev-mode + the dev `infra-credentials` static Secret → external-secrets from rask's Vault.
- The `dex` demo IdP → rask's real IdP (or keep for local-only).

## lance-ray seam contract (so the real job drops in)
The dummy producer/movers define the contract the real Ray Data jobs must reproduce **exactly**:

- **Producer (head):** write the raw Lance dataset, then **publish ONE OpenLineage run event** to the Dapr
  pubsub `lineage-pubsub` / topic `lineage.events.v1` — `inputs=[]` → `outputs=[raw_events]`, the `WROTE` edge
  carrying the **Lance version** facet (`DatasetVersionDatasetFacet`). **That is all the real Ray job does.**
  ⚠️ **It must NOT publish `medallion.raw` itself** — post-B2 the deployed lance-ray app *subscribes* to the
  lineage topic (`/raw-arrival`) and publishes the first `medallion.raw` trigger when it sees a raw-namespace
  write. A job that also published `medallion.raw` would **double-fire the cascade**. The head is event-driven:
  emit the raw-write event; the arrival subscription does the triggering.
- **Each mover:** subscribe to its upstream trigger → transform (read the from-stage Lance version-range as a
  CDF, write the to-stage) → emit the **`DERIVED_FROM`** OpenLineage edge → publish the next trigger.
- **Gold mover (terminal):** write the gold dataset **with the embedded `lineage` JSONB column** (per
  `scripts/medallion_demo.py: write_gold`) → no next trigger. This is the durable, exportable artifact.
- **Authz:** when `MEDALLION_FGA_ENABLED`, the mover checks `can_create_table` (writer) / `can_promote`
  (validator, silver→gold) as its **service identity** before emitting; unauthorized → `DROP`.
- **Creds:** the job authenticates with **workload identity** (KubeRay projected SA / OIDC token) and vends
  short-TTL, table-scoped creds via the catalog `POST /v1/table/{id}/credentials` (web_identity flow). **No
  durable secret on compute.**

Reproduce those four behaviors in the Ray Data job and the cascade keeps working unchanged.

## Verification (the merge is correct when…)
- `scripts/governance_e2e.sh` + the medallion e2e run **against rask's CNPG + rustfs-operator stores** (not the
  in-cluster hand-rolled ones) and stay green.
- `tests/integration/test_spec_conformance.py` still passes (catalog surface intact).
- A real lance-ray run produces a **gold dataset with the JSONB lineage** + `/reconcile` returns `in_sync`
  against the on-disk Lance version.
- `helm template` of rask's chart shows the catalog/lineage/medallion/compaction workloads pointing at
  `<release>-postgres` / `<release>-rustfs`, with **no in-cluster DNS leaks** and **no plaintext secrets**.

## Open decisions (resolve before/early in the merge)
1. **AGE on CNPG** — custom AGE image vs separate operand vs Lance-native graph (`docs/DECISIONS.md` #age-on-cnpg-vs-lance-native-graph-the-lineage-store-decision). Affects §1.
2. **Tenancy** — this repo is single-warehouse (`warehouse:lance_catalog`); rask is single implicit `default`
   project. Confirm one warehouse-per-deploy stays the model (no multi-warehouse routing).
3. **Catalog 501s** — the **7** genuinely backend-stubbed ops (`docs/COVERAGE.md`: rename / backfill /
   alter_transaction / MV create+refresh / batch-create+batch-commit versions) stay 501 until the upstream
   Rust `DirectoryNamespace` (or a REST/managed backend) implements them — a parallel upstream contribution,
   independent of the merge. (Was "13"; version describe/create/delete + branches are now backed — see the
   COVERAGE correction.)
4. **Observability** — share rask's one GreptimeDB or keep separate per workload.
