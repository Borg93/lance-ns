# Backup & restore runbook

How the estate is backed up, and the **order-sensitive** procedure to restore it. Closes the "no restore
procedure anywhere" gap (P4). The restore steps below are authored from the backup artifacts + Apache AGE's
requirements; **they MUST be validated once in a real restore drill** before being trusted in an incident —
that drill is the remaining P4 done-condition (needs a live throwaway cluster).

> The in-cluster backups are the SELF-CONTAINED-prod path. If you externalize to CloudNativePG (Postgres)
> and a managed S3 / rustfs-operator (object store), use THEIR PITR + snapshots instead — set
> `backups.pgDump.enabled=false` + `backups.volumeSnapshot.enabled=false`. This runbook is for the
> in-cluster path.

## What is backed up (and what is NOT)

| Artifact | What | Where | Template |
|---|---|---|---|
| **pg_dump** (gzip) | the `lineage` DB (AGE graph + events/reads tables) **and** the `openfga` DB (authz tuples) | RustFS S3 `_backups/pg/<UTC>/` | `backup-pg.yaml` (CronJob, `backups.pgDump`) |
| **VolumeSnapshot** | the RustFS data PVC = the **Lance lakehouse** (all medallion + registry data) | cluster CSI VolumeSnapshot | `backup-snapshot.yaml` (`backups.volumeSnapshot`) |

**Not backed up** (accept the loss window or externalize — see [GOAL-production-readiness.md](GOAL-production-readiness.md) P4/P7):
GreptimeDB local WAL/metadata (metrics — reconstructable), OpenBao's file PVC (P4 gap — back up the unseal
material out-of-band), and note the pg_dump lands on RustFS, so a **total RustFS loss loses both the Lance
data AND the DB dumps** unless you also ship the dumps off-cluster (P4 "fate-sharing" gap).

## Consistency: restore AGE + RustFS as a pair

The lineage graph (AGE) references Lance datasets that live in RustFS; the registry (RustFS) is described by
the catalog. Restoring one far from the other leaves dangling provenance. **Restore the pg_dump and the
RustFS snapshot from the SAME backup window**, and expect the reconcile sweep to converge minor drift
(storage↔graph) afterward.

## Restore — Postgres (AGE lineage graph + OpenFGA)

The critical AGE detail: a plain `pg_dump -d lineage` captures `ag_catalog`, the per-graph schema, and the
label tables, **but the target must have the `age` extension available and loaded**, and the graph catalog
must be consistent after load. Do NOT `psql < dump` into a database that already has a different `lineage`
graph — drop/recreate the DB first.

1. **Fetch the dump** from S3: `mc cp rfs/<bucket>/_backups/pg/<UTC>/lineage.sql.gz .` (and `openfga.sql.gz`).
2. **Recreate the target DB** clean (managed PG or the in-cluster `age-postgres`):
   `DROP DATABASE IF EXISTS lineage; CREATE DATABASE lineage;`
3. **Ensure the extension is installable** in the target (the AGE image ships it):
   `psql -d lineage -c "CREATE EXTENSION IF NOT EXISTS age;"`
4. **Restore**: `gunzip -c lineage.sql.gz | psql -d lineage`. (The dump recreates `ag_catalog`, the graph
   schema, and the label tables.)
5. **Verify the graph is real, not just present**:
   ```sql
   LOAD 'age'; SET search_path = ag_catalog, "$user", public;
   SELECT name FROM ag_graph;                    -- must list 'lineage'
   SELECT * FROM cypher('lineage', $$ MATCH (d:Dataset) RETURN count(d) $$) AS (n agtype);
   ```
   A non-zero Dataset count + the graph name confirms the labels restored, not just the metadata rows.
6. Repeat 1–4 for `openfga` (no AGE steps — it's plain relational).
7. **App recovery is automatic**: on next boot lineage runs `ensure_graph()` (a no-op if step 4 restored the
   graph) + `ensure_graph_constraints()`, and `/readyz` gates on the graph being queryable (P1/P2a) — so a
   half-restored graph fails readiness loudly rather than serving silently.

**If step 5 shows the graph metadata but zero labels** — the known plain-pg_dump-of-AGE hazard — restore is
NOT trusted: switch the backup to an AGE-aware dump (per-graph `SELECT * FROM ag_catalog.agtype ...` export
or CloudNativePG logical backup with the extension) and re-drill. **This is exactly why the drill is
mandatory before relying on this path.**

## Restore — RustFS (the Lance lakehouse)

1. Provision a new PVC from the VolumeSnapshot (`dataSource: {kind: VolumeSnapshot, name: <snap>}`).
2. Point the `rustfs` StatefulSet at it (or restore into the existing PVC per your CSI driver's clone flow).
3. Restart `rustfs`; then `catalog`/`lineage`/movers reconnect (their `/readyz` gates hold them out until the
   object store answers).

## After restore

- Watch `/readyz` on catalog + lineage flip to 200 (pool AND graph healthy).
- Drive one read (`/runs`, a dataset `/producers`) to confirm provenance resolves against the restored data.
- Let the reconcile sweep run once to converge any storage↔graph drift from a slightly-off backup pair.
- See [RUNBOOK-oncall.md](RUNBOOK-oncall.md) for the failure modes you may hit during recovery.
