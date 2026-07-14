# GOAL: catalog + lakehouse parity (build items #1–#5 + control plane)

**Set 2026-07-13.** Source: the competitive benchmark vs Lakekeeper / Unity / Polaris / Gravitino,
re-grounded against the actual code (5 scout audits) and a deep read of the Lance format spec, guide,
and Namespace REST spec (`docs/` synthesis; `lance_docs/`). This doc is the **contract**: each item has a
current-state (built vs gap), the Lance-native technique, and a **testable completion condition** an
end-to-end run can assert. Build order is dependency-driven (§Build order).

> **Framing correction (important).** The benchmark was analysis-from-a-distance and over-stated the
> gaps. In almost every item the *mechanism is already built and merged*; the gap is **activation** —
> emit the facet, flip the default, seed the tuple, provision the bucket, close the auth. That makes
> #1–#5 achievable incrementally, not a greenfield rebuild.

---

## Control-plane vs data-plane architecture (the prod split)

The FGA model **already encodes** the split; the Namespace REST op-index (`Namespace | Table | Index |
Metadata | Data | Transaction`) is the taxonomy. Prod-viable separation:

| Plane | Operations | Authorized by | Our components |
|---|---|---|---|
| **Admin / provisioning** | create tenant/team, **create warehouse (provision bucket, register `base_uri`, stamp `2.2`+stable-row-ids)**, create/drop namespace, register manifest store, manage FGA model/tuples | platform admin (`project` admin, `warehouse`/`namespace` admin relations) | catalog `namespaces.py`, OpenFGA, chart/GitOps |
| **Control / coordination** | the **manifest-version commit** (`CreateTableVersion` / put-if-not-exists — the single serialization point), `RenameTable`, `Declare`/`Deregister`, branch/tag create/update, `Restore`, `Clone`, credential vending, DDL (`add/alter/drop_columns`, `merge`) | table-scoped FGA (`can_commit`/`can_promote`/`can_restore`/`can_create_branch`) — **authorize the commit call, not the bytes** | catalog commit endpoints, `views.py`/`branches.py`/`tags.py`/`transactions.py`, vending |
| **Data** | `write_fragments` (client→bucket direct), scans/`Query`, `Insert`/`Merge`/`Update`/`Delete`, MV `refresh`, blob read | data-scoped FGA (`can_write`/`can_read`) — bytes flow client↔store with **vended, expiring** creds, never through the server | medallion movers / Ray workers / direct clients; catalog only vends + commits |
| **Eventing** | lineage outbox → Dapr publish → lineage consumer → AGE | trusted internal channel (Dapr → NATS) | Dapr, lineage svc |

**Net rule:** *authorize the manifest commit and the provisioning ops; let bytes go direct under scoped
creds.* This is exactly the Lakekeeper/Polaris cut. **What we lack for a prod control plane:** (a) an
**admin API/UI to actually provision** tenants/warehouses + manage grants (today grants are
enforcement-only, no managed surface) — see #3; (b) the physical **bucket-per-warehouse** to back it.

---

## The five items

### #1 — Column-level lineage from the live cascade
- **State.** Edge STORE done & merged (#24): `(:Column)-[:DERIVED_FROM_COLUMN]→(:Column)`, facet parser
  (`lineage/models.py::column_lineage_edges`), read endpoints (`columns.py`), **and the frontend column
  view** all exist. Gap: **producers never emit the `columnLineage` facet** — only `lineage/seed.py`
  (demo) does. Live runs create zero column edges.
- **Technique.** Add `column_lineage_facet(producer, edges)` to `common/openlineage.py`. Medallion
  `transform_stage` is generic (carry-forward + stamp `stage` + derive blob artifacts), so it can
  **declare** edges: identity `upstream.X→downstream.X` for carried columns; `payload→thumbnail`,
  `payload→embedding` for derived artifacts. Attach to the output dataset in `build_run_event`.
- **Done when.** A real bronze→silver transform (auth ON) makes
  `GET /v1/datasets/{silver}/columns/{col}/upstream` return the input column, a Cypher probe shows the
  `DERIVED_FROM_COLUMN` edge, the facet originates from the **producer** RunEvent (not `seed.py`), and
  the frontend "columns" view renders the field-to-field edges. Renaming the input column leaves the
  edge intact (field-id-stable).

### #2 — Client-direct writes as the default data plane
- **State.** Plumbing built: `WebIdentityVendor` (RustFS-native OIDC→STS), `POST /{id}/credentials?tier=write`,
  and metadata-only commit (`POST /{id}/version/create` with `manifestPath`, `batch-commit`). Default is
  `vending_mode="mode_b"` (server byte-proxy, vends nothing) and the SDK convenience writers still POST
  Arrow bytes to `/create`,`/insert`.
- **Technique.** 3-phase Lance-native: `lance.fragment.write_fragments(data, uri, schema)` →
  `FragmentMetadata.to_json()` over the wire → catalog `LanceDataset.commit(uri, Append/Overwrite,
  read_version=N)` (metadata only). Flip default to `web_identity`; steer the client write path to
  *vend → direct-write → commit*; keep byte-proxy read (`/query`,`/blobs`) as credential-less fallback;
  keep blob-v2 create server-side (`_create_blob_table` — 2.2 must be centralized).
- **Done when.** A write drives end-to-end with **zero dataset-byte ingress at the coordinator** (only
  `FragmentMetadata` JSON crosses the wire; commit is `read_version`-based). Two concurrent `Append`
  clients both succeed (auto-rebase); a stale `read_version` returns 409/`ConcurrentModification` and
  retries to success. `dataplane.create_table`'s server-side Arrow decode is gone for non-blob schemas.

### #3 — Physical multi-tenancy (warehouse = runtime-provisioned bucket)
- **State.** Medallion **zones already split** (raw→`lance-source`, gold→`lance-sink`). Catalog is still
  single-root `LANCE_REST_ROOT=s3://lance-catalog`; "warehouse" is a logical FGA root, not a bucket. No
  warehouse-create API exists.
- **Technique.** Warehouse-create (control plane) provisions the bucket (RustFS admin), registers it as
  the warehouse `base_uri`, and **stamps create-time policy** (`data_storage_version="2.2"` +
  `enable_stable_row_ids`) at the fresh-bucket boundary. A dataset is self-contained under one root
  (relative refs), so bucket-per-warehouse needs zero manifest surgery. `base_paths[]`/`Clone(is_shallow)`
  for cross-bucket/shallow variants.
- **Done when.** Two warehouses created via the admin API are backed by **distinct buckets** (distinct
  `base_uri`); a table in warehouse A is physically absent from B's bucket; new datasets report `2.2` +
  `FLAG_STABLE_ROW_IDS`; with `LANCE_OBJECT_STORE_METRICS_LABEL=full` each warehouse is a distinct
  `base` metric series.

### #4 — Transactional outbox + DLQ for lineage
- **State.** DLQ **already exists** (Dapr-native parking, default-on) + a reconcile back-fill
  (`reconcile.py`, #23) that recovers version+schema (not inputs/author/columnLineage). No transactional
  outbox — commit-then-publish-in-process crash window is real (catalog has no DB).
- **Technique.** Anchor the outbox on the durable Lance commit: in the same txn as `CreateTableVersion`/
  manifest commit write an outbox row keyed `(dataset_uri, committed_version, transaction_uuid)`; a relay
  publishes + advances a `last_published_version` cursor; the reconciler republishes the version gap on
  crash (`transaction_uuid` = idempotency key → MERGE no-op on redelivery). Watch the **ref plane** too
  (tag/branch create emits no version).
- **Done when.** A crash injected *between* the commit and the Dapr publish leaves (a) the write durable
  (version advanced, `_transactions/*.txn` present) and (b) after recovery the lineage event in AGE
  **exactly once** (idempotent on `run_id`/`transaction_uuid`) — no duplicate `WROTE`. A permanently
  failing publish lands in the DLQ keyed by `version+uuid`, queryable, not lost.

### #5 — Housekeeping
- **(a) `enable_stable_row_ids` on catalog create.** Create-time-only (silently no-ops later; verify
  `FLAG_STABLE_ROW_IDS` bit 2). Set on the blob create path; native-create path needs routing through a
  direct write or `new_table_enable_stable_row_ids` connect option. **Done:** a catalog-created table
  reports the flag set; `_rowid` survives compaction.
- **(b) `rename_table` 501 → 200.** 501 is off-spec (spec "unsupported" = 406). Implement in-process
  (`RenameTableRequest{new_table_name, new_namespace_id}` — *not* `new_id`); FGA revoke-source/seed-dest
  exists. **Done:** rename returns 200; table discoverable under new id, gone under old; onto existing
  name → 409; missing → 404; tuples migrated.
- **(c) Real FGA types for MV + transaction.** Today aliased to `table` (stopgap); **transactions
  always-deny** (check a `table:<txn-id>` object nothing seeds). Add `materialized_view` (`can_refresh`)
  and `transaction` (`can_set_status`/`can_cancel` vs `can_set_property`) types; seed transaction
  ownership; add `can_create_branch`/`can_create_tag`/`can_restore` table sub-relations (restore =
  admin-tier). **Done:** `.fga.yaml` check tests pass; a plain writer is denied restore/branch.
- **(d) Doc truth-up.** Retire stale "no DLQ" comments; cite `new_table_name`/`new_namespace_id`; record
  `data_storage_version`/`enable_stable_row_ids` create-time immutability; note 501 is off-spec.
- **(e) Auth on GreptimeDB/Perses.** Both open today; prod Ingress→gateway exposes `/greptime/` (raw
  SQL/ingest) + `/perses/` **unauthenticated**. Fix: Perses `enable_auth` (Dex) + GreptimeDB
  `auth.enabled` (propagate creds to OTLP/Vector/Perses clients) and/or nginx `auth_basic` edge stopgap.
  Separately: bump `pylance→pylance[otel]` 9.x to light up `instrument_lance_metrics()` (already wired in
  all 5 lifespans). **Done:** an unauthenticated request to either is rejected at the gateway.

---

## Build order (dependency-driven)

1. **#5(a)** stable-row-ids on create — foundational, create-time-only (any wrong table must be recreated).
2. **#3** per-warehouse bucket — the fresh-bucket boundary is the clean seam to enforce the 2.2+row-id policy.
3. **#2** client-direct writes — depends on #3's `base_uri` + vending; the plane split materializes here.
4. **#4** outbox + DLQ — anchor on #2's `CreateTableVersion` commit (build after #2 to avoid retrofitting).
5. **#1** producer emit — mostly independent (consumer done); can run in parallel.
6. **#5(b–e)** rename, FGA types, doc truth-up, auth+obs — parallelizable housekeeping.

## Landmines (from the spec read)
- `enable_stable_row_ids` **create-time-only**, silently no-ops later → verify `FLAG_STABLE_ROW_IDS`.
- `data_storage_version` **immutable per dataset**; 2.2 needed for blob-v2 (why blob create stays server-side).
- Secondary indices reference **row address**, not `_rowid`; compaction invalidates them (stable-row-id-for-index is experimental).
- Conflict matrix is **per-op**: `Append`↔`Append` rebases; `Overwrite`/`Restore` don't — retry loop must classify.
- **Ref-plane mutations (tag/branch) emit no version** → invisible to a version-tailing outbox.
- Implement to the **model files**, not the prose (`new_table_name`, not `new_id`).

## Status (2026-07-14 — code + unit/integration + audit verified; live-drive pending, no cluster up)
- [x] **#1** producer emit — in-process AND Ray path (`measure_stage` reconstructs edges from on-disk schemas)
- [ ] #2 client-direct · [ ] #3 per-warehouse bucket · [ ] #4 outbox+DLQ — *not built (live-only completion conditions)*
- [x] **#5a** stable-row-ids · [x] **#5b** rename (in-process, data-safe) · [x] **#5c** FGA types (MV + transaction)
- [x] **#5d** doc truth-up · [x] **#5e** obs edge-auth
- [x] Frontend: field-level column-lineage panel (surfaces #1)
- **Audit:** 3 adversarial rounds, 8 confirmed bugs (6 → 2 → 0), each fixed with a regression test that fails
  on the old code. Full unit+integration suite green (636); `ruff` + `ty` clean.
- **Remaining before "done-done":** (a) live-drive on a kind cluster to prove the running system, not just
  the tests; (b) build #2/#3/#4. Both need a cluster.
</content>
</invoke>
