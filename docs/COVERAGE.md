# Catalog coverage — backend-backed validation (2026-06-30)

Authoritative result of a **live probe** against a real native pylance `DirectoryNamespace` (create a
namespace + table, then call every op and classify 200 vs 501). Routes are 100% wired (54/54 spec ops);
this measures which are **backend-backed (200)** vs **spec-correct 501** because the native Rust backend
stubs them. Dispatch: most ops go to `native` (the Rust `DirectoryNamespace`); a few go to the in-process
`dataplane` (pylance, always 200) — see `services/catalog/services/{native,dataplane}.py`.

**Tally: 41 / 54 backed (200), 13 spec-correct 501.** `uv run pytest` → 208 passed, 15 skipped.

| Group | Backed (200) | 501 (native stub) |
|-------|--------------|-------------------|
| Namespaces (5) | all 5 | — |
| Tables lifecycle (10) | 9 | `rename_table` |
| Data CRUD (9) | all 9 (`update`/`delete` via dataplane) | — |
| Columns (6) | 5 (add/alter/drop/update-field-metadata/schema-metadata via dataplane) | `backfill_columns` |
| Indices (5) | all 5 | — |
| Tags (5) | all 5 (dataplane) | — |
| Versions (6) | 1 (`list`) | `create` / `describe` / `delete` / batch-create / batch-commit |
| Branches (3) | — | `list` / `create` / `delete` |
| Transactions (2) | 1 (`describe`) | `alter_transaction` |
| Materialized views (2) | — | `create` / `refresh` |
| Credentials + stats (2+) | all | — |

The 13 501s are **backend limits, not catalog gaps** — the native `DirectoryNamespace` doesn't implement
branch ops, MV ops, version mutation, rename, or backfill. The catalog is a faithful REST surface over what
pylance provides; if/when pylance backs these (or the in-cluster dataplane is extended), they flip to 200
with no route change. `rename_table` 501s at the native call, so its FGA-revoke wiring is defensive (it only
runs if rename ever succeeds).

**Can the in-process dataplane back them (like it does update/delete/columns/tags)? No — investigated 2026-06-30:**
the 13 are genuine *upstream* limits, not in-process-fillable:
- **Version ops** (`create`/`describe`/`delete`/batch) — `create_table_version` has no clean pylance analog
  (Lance versions are *write-created*, not declared); `cleanup_old_versions` deletes by *age/count*, not the
  arbitrary version records `BatchDeleteTableVersions` wants; and even `describe_table_version` can't be
  backed cleanly — the spec's `TableVersion` **requires `manifest_path`**, which pylance's public API does
  not expose (only `{version, timestamp, metadata}`). Constructing it from Lance's (V2-hash-prefixed)
  internals would be fragile, so it stays a 501.
- **Materialized views** + **branches** — no public pylance API.
- **`rename_table` / `backfill_columns`** — stubbed in the native Rust namespace.

So further catalog completeness needs UPSTREAM work in pylance / the Rust `DirectoryNamespace`, not changes
in this repo. The catalog is complete **to the limit of its backend**.

## Durable-artifact + recovery
- **Gold embeds lineage as JSONB** + sits on the durable S3 tier — but TODAY this is produced **only by the
  demo driver** (`medallion_demo.py: write_gold`), **not the deployed service**. The deployed medallion
  movers are **dummy emitters** (provenance only, no Lance data write). This is **by design**: the real
  gold-writing producer is **lance-ray** — a Ray Data job that lands when this merges into rask (rask's
  KubeRay cluster). The deployed pipeline today validates the *event-driven + provenance* seam; the *data*
  production is the rask integration (`todo.md` P1 #6, lance-ray promotion).
- **Stage recovery works** — `restore_table` (v1→v3 verified) on the native backend; the medallion `WROTE`
  edge records the Lance version (`DatasetVersionDatasetFacet`); `/reconcile` anchors gold to the on-disk
  `latest_write_version`.
- **Retention nuance:** the compaction cron runs `cleanup_old_versions(older_than=7d)` over **every** dataset
  (gold included). It always keeps the **current** version (no data loss), but caps **time-travel depth** at
  7 days uniformly — there is no per-stage retention. If gold needs a longer recovery window than
  intermediate stages, make `olderThanDays` stage-aware. (Not a durability violation — the system-of-record
  is preserved; only old version *history* is GC'd.)

## Low coupling (the rask-mergeability bar) — PASS
Zero cross-service imports; `common` imports no service; services share only the cross-cutting lib
(`fga`/`secrets`/`dapr_auth`/`oidc`/`exceptions`) and talk only over Dapr/NATS + HTTP. The lakehouse +
event-driven estate is a self-contained, contributable unit.

## Lakekeeper diff (for the ephemeral spin-up-per-workload model)
**N/A by design:** multi-warehouse data plane, control-plane management API, soft-delete/undrop (replaced by
Lance version time-travel + `restore_table`), user/role admin API, Postgres task queue (NATS+Dapr instead).
**Ahead of Lakekeeper:** the lineage moat (reconcile, column lineage, gold whole-history JSONB) +
web-identity credential vending. One caveat: a *long-lived single shared* cluster would want runtime
grant/role admin — N/A only while the model stays spin-up-per-workload.
