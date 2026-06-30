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

| Service | Why external in prod | How |
|---------|----------------------|-----|
| **S3 lakehouse** | the permanent ingest+export surface; you want a managed, replicated, lifecycle-policied object store (AWS S3 / a RustFS or MinIO cluster) | `rustfs.enabled=false` + point `LANCE_S3_ENDPOINT` (+ lineage/compaction S3 env) at the external store |
| **Postgres (AGE)** | a managed DB (RDS/Cloud SQL/CNPG) for backups, HA, PITR | `age.enabled=false` + point `LINEAGE_DATABASE_URL` + the OpenFGA datastore at it |
| **OpenBao / secrets** | a hardened external Vault / cloud KMS; an operator populates the k8s `infra-credentials` Secret from it (external-secrets / the Vault agent) | ⚠️ **not a safe flip yet** — today `openbao.enabled=false` makes the apps fall back to PLAINTEXT secrets in pod env (re-opens the closed leak); the app branches read `.Values`, not the infra Secret. Needs the secretKeyRef-from-infra-Secret wiring first. |
| **Observability** (GreptimeDB / Vector / Perses) | you don't want observability to die with the cluster it observes — run it on a separate platform/cluster | `observability.enabled=false` + point OTLP at the external collector/store |

> ⚠️ **The tier-3 rows describe the intended mechanism, not a present-day knob.** Today only the
> `*.enabled=false` toggle exists; the matching external-endpoint overrides (`LANCE_S3_ENDPOINT`,
> `LINEAGE_DATABASE_URL`, the OTLP endpoint, the OpenBao address) are **not yet wired** — disabling a
> component removes the in-cluster copy but the apps still target its in-cluster DNS name. Wiring those
> overrides is the remaining chart work (mirrored in the EXTERNALIZE note in `values-prod.yaml`).

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
