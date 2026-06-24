# System sketch — where we are, the holes, and how we differ from Lakekeeper

> Living status doc (bird's-eye). Detailed design: [`ARCHITECTURE.md`](ARCHITECTURE.md)
> (catalog) and [`LINEAGE.md`](LINEAGE.md) (provenance). Roadmap: [`../todo.md`](../todo.md).
> This file = the sketch of everything + the gap register + the Lakekeeper diff.

## 1. The whole system at a glance

**Three planes, three governance axes, one identity** (the catalog `table:<id>`).

```
                         OIDC (Dex / IdP)        OpenBao (secrets — planned)
                               │                        │
   clients ──Bearer JWT──▶  ┌──┴─────────────────────────────────┐
   (LanceDB SDK,            │  CATALOG  (control plane, FastAPI)  │
    lance-ray, apps)        │  authn → authz → locate → record   │
                            │  never moves data                  │
                            └───┬───────────────┬────────────────┘
                                │               │ describe_table → location (+creds via
              OpenFGA ◀─can_*?──┘               │ CredentialVendor: ModeB today)
              (Postgres)                        ▼
                                       object store  (HCP prod / MinIO dev)   ── DATA PLANE ──
                                          ▲  compute (lance-ray / pylance) moves bytes
                                          │  (Mode B: via catalog endpoints today)
   compute/ETL jobs ──OpenLineage──▶  ┌──┴──────────────────────────┐
   (emit run events)                  │  LINEAGE  (provenance plane) │  ── separate service ──
                                       │  ingest → Apache AGE graph   │
                                       └──────────────┬──────────────┘
                                            AGE / Postgres (its OWN db)
```

**Three axes — same object, governed three ways:**

| Question | System | Identity |
|---|---|---|
| **who may** read/write/commit | OpenFGA `can_*` on `table:<id>` | `table:bronze$images` |
| **what / when** changed | Lance versions + tags (immutable, time-travel) | same dataset |
| **how / from where / by whom** | OpenLineage → Apache AGE graph | dataset node `name` = `table:<id>` |

**Medallion flow (target, end-to-end):**
`ingest → bronze`, then `promote bronze→silver→gold` as lance-ray jobs. Each hop:
authz on the catalog → creds via the vendor (Mode B today) → bytes moved by the engine →
emit an OpenLineage event. Layers are **separate Lance tables** (namespaces); promotion is a
**compute client**, never a catalog endpoint.

## 2. Component status

| Component | What | Status |
|---|---|---|
| Catalog REST API | FastAPI over pylance `DirectoryNamespace` (Lance Namespace spec) | ✅ built |
| OIDC authn | PyJWT/JWKS, fail-closed | ✅ built |
| OpenFGA authz | op→`can_*`, concentric+cascade, roles-as-`#assignee`, `grant_on_create` | ✅ built |
| Resilience | transient-aware retries; network → 503 (never 500) | ✅ built |
| `CredentialVendor` | pluggable ModeB / StaticPrefix / Sts (`app/core/vending.py`) | ✅ scaffolded, ⛔ not wired |
| Maintenance read-only | 503+Retry-After middleware (`app/api/maintenance.py`) | ✅ built (default off) |
| Lineage service | OpenLineage ingest → AGE graph (`lineage/`) | ✅ built, ⚠️ open + undeployed |
| OpenBao SecretStore | secrets out of env | ⛔ not built |
| lance-ray jobs | promotion + compaction (the medallion movement) | ⛔ not built |
| Governance P1 | `project` type + 3-axis (teams×projects×layers) | 🔶 planned |
| OTel / NATS / Dapr | observability / events / durable workflows | 🔶 deferred |

## 3. Holes / what's missing (gap register)

| # | Gap | Plane/axis | Risk if left | Priority |
|---|---|---|---|---|
| 1 | **Lineage read endpoints unauthenticated** | provenance | leaks the data estate (which tables exist, how they connect, who ran what) | **P0** |
| 2 | **Lineage ingest endpoint unauthenticated** | provenance | anyone can inject false provenance / flood the graph (no producer trust) | **P0** |
| 3 | CredentialVendor not wired into `describe_table` | data | vending unavailable; only Mode B (via catalog) usable | P1 |
| 4 | HCP plug not finalized (Mode B vs static keys) | data | medallion jobs can't reach storage with scoping decided | P1 |
| 5 | Secrets in env (no OpenBao SecretStore) | security | one static long-lived S3 key in env; no rotation/least-priv | P1 |
| 6 | lance-ray promotion + compaction jobs absent | data/medallion | the actual bronze→silver→gold movement doesn't exist yet | P1 |
| 7 | Lineage not deployed (no image / compose service) | provenance | runs only via `uvicorn`; not in the stack | P1 |
| 8 | No routes-vs-spec conformance test | control | spec drift goes unnoticed (we have a known conformance gap) | P1 |
| 9 | OpenFGA model hand-edited (`.fga`/`.json`) | authz | no versioned migration / reconcile-from-catalog → risky to evolve to 3-axis | P1 |
| 10 | No write idempotency | control | retried promotion/ingest jobs can double-apply | P2 |
| 11 | Governance P1 (`project` + 3-axis) not built | authz | teams×projects×layers model not yet expressible | P1 |
| 12 | No OTel / NATS async ingest / Dapr | obs/infra | limited prod observability; synchronous lineage ingest | 🔶 |

## 4. Incoming lineage feature — review (the 3 pulled commits)

- `fa44da5` — Apache AGE store: `docker-compose.lineage.yml` (PG16+AGE, pinned — PG18 crashes
  `create_graph`) + `lineage-init.sql` (enable AGE, `create_graph('lineage')`).
- `5e5898c` — the service: `models/schemas/age/repository/main` + producer `seed.py` + tests;
  updated `ARCHITECTURE.md` §7/§9 lineage status → built.
- `e176645` — docs: the read-side authz design + open-endpoints caveat in `LINEAGE.md`.

**Strengths (verified by reading the code):** Cypher-injection-safe (`age.py:56-95`: graph name
`_IDENT`-validated + `sql.Literal`; Cypher `LiteralString`-typed; user input only as `agtype`
bind params, never interpolated); layered (no Cypher in endpoints); transactional ingest;
**DB-per-service** (own AGE Postgres, never co-mingled with OpenFGA's); `author` = OIDC sub;
unit + e2e tested; ruff/ty clean.

**Holes:** gaps #1 and #2 above — read *and* ingest are open. The docs flag reads; the **ingest
trust gap is additional** and must be closed when real jobs emit (service token / OIDC on the
producer).

## 5. Diff vs Lakekeeper — what we keep, what we do differently

**Our core principles:** thin control-plane catalog (authorize + locate + record, never moves
data) · control/data/provenance plane separation · **vending-first, pluggable** credentials ·
relational OpenFGA authz (one identity across three axes) · fail-closed + least-privilege +
secrets in OpenBao · small & Pythonic (FastAPI + pylance) over a large multi-warehouse service ·
DB-per-service · spec-faithful (Lance Namespace REST).

| Capability | Lakekeeper (real, cloned `lakekeeper-ref`) | Us | Verdict |
|---|---|---|---|
| Catalog impl | Rust, multi-warehouse, many crates | Python FastAPI over pylance, ~focused | **smaller, Lance-native** |
| Table format | Iceberg tables (+ generic tables) | Lance datasets (vector / blob / medallion) | **our domain** |
| Control vs data plane | catalog never moves data | same + **Mode B** server-mediated fallback | we add Mode B (for HCP) |
| Credential vending | STS (S3) · SAS (Azure) · bearer (GCS) + remote signing | pluggable `CredentialVendor` (ModeB/Static/Sts), vending-first | **design matches**; HCP→ModeB (Lakekeeper has no HCP plug) |
| AuthZ model | OpenFGA v4: hierarchy/ownership tuple split, golden drift tests, **reconcile-from-catalog**, **versioned model migration** | OpenFGA `can_*` + cascade + roles + `grant_on_create` | core matches; **ADOPT** reconcile + versioned migration + golden drift tests |
| Lineage | emits **CloudEvents** → external consumer (Kafka/NATS); no built-in graph | **built-in lightweight-Marquez** (OpenLineage → AGE openCypher) | **we're more integrated** |
| Secrets | pluggable `SecretStore` (Postgres-encrypted + Vault KV2) | planned **OpenBao** (KV v2, Vault-compatible) | **ADOPT** (OpenBao drops into the KV2 pattern) |
| Maintenance read-only mode | `api/maintenance.rs` | ✅ `app/api/maintenance.py` | **matched** |
| Routes-vs-spec test | `test_endpoint_completeness` (enum vs OpenAPI) | ⛔ none | **ADOPT** (closes our conformance gap) |
| Idempotency | `idempotency_record` table | ⛔ none | **ADOPT** for jobs |
| Events backend | `CloudEventBackend` (NATS/Kafka) + EventDispatcher | ⛔ (lineage ingest is direct POST) | adopt as the OpenLineage emit hook later |
| Audit | `PrivilegeSource` + instance-admin bypass | partial | consider |

> A **file:line-cited adoption backlog** generated from the real cloned source by study
> `wfb25lg74` will be appended below as **§6** when it completes.
