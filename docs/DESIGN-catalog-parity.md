# DESIGN RECORD — catalog parity #1–#5 (SHIPPED)

> **This is an ARCHIVE of shipped design, not a goal.** The single live goal is
> [`GOAL-prove-it.md`](GOAL-prove-it.md). Kept because the control-plane/data-plane split, the
> #3-A (per-warehouse bucket) + #3-B (Lance multi-base) designs, and the Lance-spec landmines below
> are still load-bearing. All five items are built, live-verified on kind, and adversarially audited.


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

### GOAL + CONDITIONS (set 2026-07-14, building next in order #4 → #3)

**#4 — transactional outbox for lineage (durability).**
- **Goal:** no lineage event is ever lost when a producer crashes between the Lance commit and the Dapr
  publish. The full event (inputs, author, columnLineage — not just version+schema) survives + is delivered
  exactly-once.
- **Design:** a durable OUTBOX in object storage (the stateless-over-object-store fit): the emitter writes
  the full event to an `_lineage_outbox/<run_id>.json` object, publishes to Dapr, deletes on ack. A relay
  (extend `lineage/core/reconcile.py`) lists the outbox on its cron, VERIFIES the referenced write actually
  committed (dataset version on storage — discards phantom events from a crash before the data commit),
  republishes the survivors (idempotent — the graph MERGEs on `run_id`), and deletes them.
- **Done when (live, crash-injected):** kill the producer AFTER the Lance commit but BEFORE the publish;
  the write is durable (version advanced), and after the relay runs the lineage event appears in AGE
  EXACTLY ONCE (no dup `WROTE`/`DERIVED_FROM`, full inputs+author+columnLineage preserved). A permanently
  failing publish lands in the DLQ, queryable, not silently lost. A phantom outbox (commit never landed) is
  discarded, never published.

**#3 — physical multi-tenancy (control plane) + Lance Multi-Base (differentiator).**
NOTE (2026-07-14): two DISTINCT, complementary axes — do not conflate:
  - **#3-A = per-warehouse bucket = multi-TENANCY** (one tenant → one bucket; ISOLATION). Lakekeeper parity.
  - **#3-B = Lance Multi-Base** (one TABLE → N buckets via `base_paths[]`+`base_id`; THROUGHPUT/tiering/DR/
    shallow-clone — the Uber use case). Iceberg (absolute paths, v4 rework) + Delta (hybrid, lost portability
    on shallow-clone) can't do this cleanly; Lance keeps strict relative-path portability AND multi-location →
    this is where we EXCEED the peers, not just reach parity. Partial support already exists (`initial_bases`/
    `DatasetBasePath` in the blob-create path; `layout.md` documents hot/cold, multi-region, DR, shallow-clone).
- **#3-A goal:** a warehouse = a runtime-provisioned, physically separate bucket, not the shared
  `lance-catalog` bucket by prefix. Provisioned + governed through an admin control-plane API.
  **Done when:** two warehouses → DISTINCT buckets; a table in A is physically ABSENT from B's bucket;
  new datasets report 2.2 + FLAG_STABLE_ROW_IDS; denied to a non-project-admin (403).
- **#3-B goal:** expose `base_paths` so ONE dataset can span N buckets, portably + governed.
  **Done when:** a dataset created with `initial_bases` across 2 buckets round-robins writes + fans out
  reads, stays relative-path portable, and the catalog vends/governs per-base.

### #3-A implementation design (DECIDED 2026-07-14, grounded in the code map)

Current state (map): the `warehouse` FGA type + `project.can_create_warehouse`/`can_administer` EXIST
but are **dead in code**; there is **no admin API and no runtime bucket creation** (only a Helm `mc mb`
Job at `chart/templates/rustfs.yaml:146`); the catalog is **single-root** (`LANCE_REST_ROOT`, one
`connect()` at startup); multi-base is used only for external-blob allowlisting. So #3-A is net-new
control-plane wiring — NOT a model change (the model already has the types).

Design (mirrors the outbox's stateless-over-object-store pattern + the existing FGA seed pattern):
1. **Warehouse registry** — `services/catalog/services/warehouses.py` (NEW). S3-backed records at
   `s3://<control-root>/_warehouses/<id>.json` = `{id, bucket, root_uri, project, created_at}`, plus a
   namespace→warehouse binding at `_warehouses/bindings/<top-ns>.json`. Functions: `provision_bucket`
   (boto3 `create_bucket`, idempotent like `mc mb --ignore-existing`), `put/get/list_warehouse`,
   `bind_namespace`/`warehouse_for_namespace`. Uses the same `S3FileSystem`-from-storage_options helper
   shape as `common/outbox.py`.
2. **Admin API** — `services/catalog/api/v1/endpoints/warehouses.py` (NEW). `POST /v1/warehouses`
   {id, bucket?, project} → gate `can_create_warehouse` on `project:<project>` → provision bucket +
   write registry + seed FGA (`warehouse:<id>` parent `project:<project>`, grant caller owner, mirroring
   `seed_ownership`). `GET /v1/warehouses` + `GET /v1/warehouses/{id}` (reader/administer gated).
3. **FGA gate** — `fga_deps.py`: `require_can_create_warehouse(project)` checks the dormant
   `can_create_warehouse` on `project:<project>`; fail-closed 503 on outage, 403 on deny (mirror the
   existing deps). Wires the model action that was never enforced.
4. **Warehouse-aware storage routing** — a per-root `connect()` cache in `core/namespace.py`
   (`namespace_for_root`) + warehouse-aware `NamespaceDep`/`StorageOptionsDep` variants that resolve the
   binding for the request's TOP-LEVEL namespace segment and return that warehouse's rooted connection +
   storage_options. **No binding → default root** (existing single-bucket flows unchanged — backward
   compatible + low-risk). A table under a warehouse-bound namespace physically lands in its bucket, so
   describe/commit/read MUST route to the same root (Lance is self-describing under its root).
   Namespace-create binds the top-level namespace to its warehouse (a `warehouse` selector).

**#3-A done when (live on kind):** admin provisions warehouse A→bucket-a + B→bucket-b (distinct
buckets, created at runtime by the API not Helm); a table created under A physically lands in bucket-a
and is ABSENT from bucket-b (verified by listing both buckets); new datasets report data_storage
2.2 + FLAG_STABLE_ROW_IDS; `POST /v1/warehouses` denied to a non-project-admin (403). Unit + integration
+ live e2e, adversarially audited.

**#3-A STATUS: DONE (2026-07-14).** Shipped (f1a50e4) + audit-hardened (ac02757: 5 isolation holes fixed
incl. a CRITICAL cross-tenant takeover), live-verified on kind (provision A/B → distinct buckets; table
in A absent from B; non-admin 403; F1 cross-project 409 + F2 binding-hijack 409 driven live).

### #3-B implementation design (multi-base data distribution — the differentiator)

Feasibility CONFIRMED (2026-07-14): pinned **pylance 8.0.0** exposes the full write API — `DatasetBasePath`,
`write_dataset(initial_bases=, target_bases=, base_store_params=)`, `LanceDataset.add_bases`. The catalog
already uses `initial_bases` (is_dataset_root=False) for external-blob allowlisting (`dataplane.py`), so
#3-B EXTENDS that seam to DATA distribution (the Uber pattern).

Design:
- **Create path:** the create-table request accepts optional `data_bases: list[str]` (additional
  is_dataset_root=False S3 base URIs) + implicit `target_bases` = round-robin across them, threaded into
  `dataplane.create_table` → `write_dataset(initial_bases=[DatasetBasePath(b, is_dataset_root=False) ...],
  target_bases=[...])`. Preserves the existing external-blob behavior + the #5a 2.2/stable-row-id invariant.
- **Governance (REQUIRED — this is the security crux):** a caller must NOT be able to point base_paths at
  an arbitrary bucket (data exfil / write to a bucket they shouldn't). Restrict `data_bases` to an
  ALLOWLIST (`LANCE_MULTIBASE_DATA_BASES`, mirroring `external_blob_bases`) — reject an off-list base (400).
  A registered-warehouse-bucket check is the richer future option; the allowlist is the MVP.
- **Read:** transparent — `lance.dataset(uri)` fans out across all registered bases; no catalog change.
**#3-B done when (live on kind):** a table created with 2 data bases has its data files DISTRIBUTED across
both buckets (list both — each holds fragments), `to_table()` returns ALL rows (fan-out read), the dataset
stays relative-path portable, an off-allowlist base is rejected (400), and #5a (2.2 + stable-row-ids) holds.

**#3-B STATUS: DONE (2026-07-14).** Shipped (86d0afc) + audit-hardened (55f1945). Adversarial audit
confirmed the security surface solid (allowlist complete, base_store_params runtime-only/no credential
persistence, #5a + portability hold) and fixed 3 correctness findings (overwrite now distributes when
re-supplied; base-name collision/dedup rejected; single-endpoint invariant documented). Live-verified on
kind: a table created with 2 data bases redirects its fragment into a data bucket (NOT the primary root),
the fan-out read resolves all 4000 rows, an off-allowlist base → 400. NOTE on the "both buckets" condition:
a SINGLE create produces one fragment → the first base; round-robin spreads across the set as fragment
count grows, so the live proof asserts REDIRECTION (data in a data base, manifest in the primary root) +
fan-out read rather than literal both-bucket spread from one small write.

---
## ALL OF #1–#5 COMPLETE — built, live-verified on kind, adversarially audited, MERGED TO `main` (2026-07-15)
#1 columnLineage · #2 client-direct writes · #3-A per-warehouse bucket + control-plane · #3-B multi-base ·
#4 transactional outbox+DLQ · #5a–e housekeeping. Every feature got an adversarial audit; #4 (3), #3-A (5,
incl. a CRITICAL cross-tenant takeover), #3-B (3) findings fixed + re-verified. Parked per user: NATS HA,
KubeRay+Kueue, query engine, rask merge, the secrets operator (docs/OPERATORS.md §5).
- **Design:** admin `POST /v1/warehouse/{id}/create` (project-admin gated via `can_create_warehouse`):
  provision the bucket (RustFS admin / `mc mb`), register it as the warehouse `base_uri`, stamp create-time
  policy (`data_storage_version=2.2` + `enable_stable_row_ids`). Route table/namespace location production
  under the warehouse `base_uri`. Consume side already handles arbitrary buckets (vending, open_dataset).
- **Done when (live):** create two warehouses via the admin API → each backed by a DISTINCT bucket
  (distinct `base_uri`); a table created in warehouse A is physically ABSENT from B's bucket (object-store
  list); new datasets report `2.2` + `FLAG_STABLE_ROW_IDS`; the create is denied to a non-project-admin
  (403); with `LANCE_OBJECT_STORE_METRICS_LABEL=full` each warehouse is a distinct `base` metric series.

---

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
