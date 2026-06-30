# Durability & deployment tiers

This makes explicit what the chart only *implied*: which parts of the system are **ephemeral compute**,
which are the **durable data** that must be backed up, and which should be **external / managed in
production**. The defaults target a local `kind` cluster; a prod deployment flips toggles to externalize the
stateful layer.

## The three tiers

### 1. Ephemeral compute — stateless, roll freely
The FastAPI services and the event plumbing hold no durable state; they can be killed, scaled, or
re-imaged at any time with no data loss.

- `catalog`, `lineage`, `medallion` (producer + 3 movers), `compaction`, `gateway`, `web`
- `dapr` control plane, `dex`

These read their config from env / OpenBao and their data from the durable tier below. Rolling them is a
no-op for data.

### 2. Durable data — must persist + be backed up
| Store | Holds | Persistence | Lifecycle |
|-------|-------|-------------|-----------|
| **RustFS / S3** | the **lakehouse** (Lance datasets) + GreptimeDB's observability bucket | **PVC** (`rustfs.persistence.enabled`, default on) | the permanent data asset — lives for months/years |
| **Apache AGE / Postgres** | the lineage graph (provenance history) + OpenFGA's authz store | PVC (`volumeClaimTemplates`) | grows with history; permanent |
| **NATS JetStream** | the catalog→lineage event buffer | PVC (`fileStore`) | transient (replay window); survives restart so no event is lost across a roll |
| **OpenBao** | secrets | PVC (prod path, `openbao.devMode=false`) | permanent; in prod usually **external** (see tier 3) |

> Before this work RustFS was `emptyDir` — the one place the *durable* asset sat on *ephemeral* storage, so
> every RustFS roll wiped the lakehouse. It is now a PVC by default.

### 3. External / managed in production
You **can** run everything in-cluster (the default), but in production the stateful + cross-cutting
services are better run as managed/external services — disable the in-cluster copy and point the apps at the
external endpoint:

| Service | Why external in prod | How (wired) |
|---------|----------------------|-----|
| **S3 lakehouse** | the permanent ingest+export surface; you want a managed, replicated, lifecycle-policied object store (AWS S3 / a RustFS or MinIO cluster) | `rustfs.enabled=false` + `rustfs.externalEndpoint=…` → catalog/lineage/compaction + vending connect there (also override `greptimedb-standalone.objectStorage.s3.endpoint`) |
| **Postgres (AGE)** | a managed DB (RDS/Cloud SQL/CNPG) for backups, HA, PITR | `age.enabled=false` + `age.externalHost=…` (+ matching user/password/dbs) → lineage DSN + the OpenFGA datastore Secret point there (also override the openfga subchart's `datastore.uri`) |
| **OpenBao / secrets — app tier** | a hardened external Vault / cloud KMS | `openbao.enabled=false` + `openbao.externalAddr=…` → the apps consume from the external Vault via their Dapr sidecar (`secretsViaDapr` keys off `externalAddr`, so there is **no** plaintext-env fallback) and the in-cluster OpenBao is not rendered |
| **infra-tier Secret** | the `infra-credentials` Secret (AGE/RustFS root creds) should come from Vault, not chart values | `externalSecrets.enabled=true` → the external-secrets.io operator syncs `<release>-infra-credentials` from Vault (the static Secret is skipped); the openfga DSN is assembled from the fetched password |
| **Observability** (GreptimeDB / Vector / Perses) | you don't want observability to die with the cluster it observes — run it on a separate platform/cluster | `observability.enabled=false` + `observability.externalOtlpEndpoint=…` → apps + Dapr export OTLP there |

> All four overrides are **wired and verified** (render-checks confirm: no in-cluster DNS leaks into app env
> when externalized; external-Vault keeps the apps on Dapr secrets with no plaintext fallback; the
> external-secrets operator owns the infra Secret with no static values). The `values-prod.yaml` EXTERNALIZE
> block shows the full set.

## Data lifecycle — what's permanent vs transient
The S3 store is permanent **infrastructure**; the *data within it* has a lifecycle:

- **Ingest point (`raw`) + export point (`gold`/catalog tables)** are **permanent surfaces** — the lakehouse
  is the durable system of record.
- **`raw` / `bronze` / `silver`** are **transient**: produced, consumed downstream, then aged out. The
  **compaction service** (a Dapr cron) runs `cleanup_old_versions()` + `compact_files()` to GC old versions
  and reclaim space, so intermediate data doesn't accumulate forever.
- **`gold` + the catalog's registered tables** are **permanent** — the curated output that lives for
  months/years and what downstream consumers + the lineage moat (`/reconcile`) are anchored to.

So: long-lived lakehouse + provenance, with a compaction/GC lifecycle aging out the intermediate layers.

## Backup strategy
- **Lakehouse (S3/RustFS)** — the highest-value asset. In prod: an external object store with versioning +
  cross-region replication + lifecycle rules. In-cluster: snapshot the RustFS PVC (`VolumeSnapshot` on a CSI
  StorageClass). Lance datasets are immutable-versioned on disk, so an object-store snapshot is consistent.
- **AGE / Postgres** — `pg_dump` / WAL archiving (managed DB does PITR); or PVC `VolumeSnapshot`.
- **OpenBao** — the file-backend PVC snapshot, or (prod) the external Vault's own backup; secrets are also
  re-derivable from the source of truth the operator populates from.
- **NATS** — transient; no backup needed (idempotent MERGE on `run_id` means a lost-then-replayed event is a
  no-op).

## Prod profile
`chart/values-prod.yaml` is a starting overlay — it flips the safe-by-default-off prod switches (sealed
OpenBao, governance on, Dapr dashboard off, ingress) and sizes the already-on durable RustFS volume, and is
where you'd disable the in-cluster stateful services + point at external endpoints once those endpoint
overrides are wired. Apply with `helm upgrade … -f chart/values.yaml -f chart/values-prod.yaml`.
