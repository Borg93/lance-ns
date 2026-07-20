# Implementation confidence + feature gaps (vs Lakekeeper & Marquez)

A thorough cross-read of `lance_docs/` (guide.md, file_format.md, ray.md, the full `ns_catalog/spec.yaml`)
against the implementation in `services/catalog` and `services/lineage`. Answers: (1) are we using the
Lance / lance-namespace APIs **correctly**? (2) what do we **lack** vs Lakekeeper (Iceberg REST catalog)
and Marquez (OpenLineage reference server) — and does it matter for a *Lance* lakehouse?

## 1. Implementation confidence — HIGH

The catalog is a faithful "Lance Catalog adapter" in the spec's own terms: a FastAPI REST server over the
native `DirectoryNamespace`, with the pylance data plane filling ops the backend stubs. Verified correct:

- **Backend construction** (`connect(impl, {root, storage.*})`) matches `supported-catalogs/lance-dir.md`.
- **Error model** — numeric `ErrorCode` → HTTP status + `code` in the problem+json body — matches `errors.md`.
- **Arrow-IPC ops** (create/insert/merge/query/count/explain) match `catalog/rest/index.md` content types.
- **Multimodal (blob-v2) create** — `create_table` picks the write path by schema (§9 P1): a `lance.blob.v2`
  column needs file format 2.2, which the native create pins at 2.1 and rejects, so it routes to a direct
  `write_dataset(data_storage_version="2.2")` (declare → write, with rollback-on-failure); every other schema
  delegates to native. Both `data_storage_version` and `enable_stable_row_ids` are **create-time immutable** —
  a dataset cannot be upgraded 2.1→2.2 nor have stable row-ids turned on in place (a later `alter` silently
  no-ops), so the 2.2 + row-id policy must be stamped at the create/fresh-bucket boundary; this is *why* blob
  create is routed server-side rather than left to a post-hoc alter. Client `storage_options` are still not
  accepted (the catalog vends storage access).
  **Serving (2026-07-12, Batch 13)**: `GET /v1/table/{id}/blobs?column=&row=[&version=]` streams blob bytes
  to credential-less consumers (browser/notebook) with RFC 9110 Range support — a `Range: bytes=…` request
  reads ONLY the window from storage via the lazy `BlobFile` (206 + `Content-Range`; 416 when unsatisfiable)
  — governed at reader-tier `can_read_data` like `/query`. Deliberately a governed proxy, not presigned URLs
  (a signed URL bypasses ReBAC for its TTL).
  **Blob modes**: managed/inline/packed/dedicated (bytes copied in) always work; **external-pointer**
  (`Blob.from_uri` outside the dataset root) is gated behind `vending.allowExternalBlobs` (default off — an
  external object's lifecycle is outside Lance's version-aware GC), and rejected with a clean 400 when off.
- **Tags / branches / versions** — `ds.tags` reference mapping (int vs `(branch, version)`), `ds.branches`,
  and the `_DICT_REQUEST_METHODS` version-marshalling fix — all match `guide.md` / `spec.yaml`.
- **Schema evolution** — `add_columns` / `alter_columns` (JSON-Arrow→`pa.DataType`) / `drop_columns`,
  `update()` reading `num_rows_updated`, `virtual_column` rejected as 501 — all correct.
- **The known 501s are spec-legitimate** (`operations/index.md` frames everything beyond the 8 basic ops as
  optional / SDK-fulfillable): `rename_table`, `backfill_columns`, `alter_transaction`,
  `batch_create/commit_table_versions`, materialized views.
- **Lineage emission** uses genuine standard OpenLineage facets with correct schema URLs; `outputStatistics`
  measured at compute time is the *right* approach — `file_format.md` confirms Lance deliberately keeps
  column stats out of the file, and `ray.md` confirms `write_lance` returns no version/stats.

### Minor deviations (none are correctness bugs; listed for a conscious decision)
| # | Deviation | Spec says | Impact |
|---|-----------|-----------|--------|
| 1 | ~~Path/body `id` mismatch silently overrides (uses path id)~~ | 400 when both present **and differ** | ✅ **fixed (#43)** — every body-carrying `{id}` route reconciles via `core/identifiers.reconcile_body_id` (the 29 override sites + rename/field-metadata/schema-metadata); a differing body id is a 400 |
| 2 | Unsupported → HTTP **501** | `UnsupportedOperationErrorResponse` is **406** | body `code:0` is correct; only the HTTP status diverges (501 is arguably cleaner) |
| 3 | ~~`exists` → **204**~~ | 200 no-content | ✅ **fixed (spec 0.9)** — both `exists` endpoints now return **200** |
| 4 | CreateTable ignores `x-lance-table-location` + `storage_options` | caller-chosen location/options | fine for single-root; completeness gap |
| 5 | ~~MergeInsert omits optional filters/`timeout`/`use_index`; `on` not enforced required~~ | full param set | ✅ **stale — already conformant** (the pylance-8/spec-0.9 upgrade added `on`/filt/`timeout`/`use_index`/`branch`, tested); residue: the FastAPI signature keeps `on` optional so the backend's own 400 answers a missing `on` (tightening it would trade a spec-true 400 for a 422 — consciously left) |
| 6 | List ops omit `delimiter` / `include_declared` | those params | ⚠️ **half-stale**: `include_declared` shipped on both table-list routes; per-request `delimiter` **consciously skipped** — deploy-fixed via `LANCE_NS_DELIMITER`, and honoring it per-request would have to thread through the router-level FGA gate too (endpoint-only support would let the gate authorize a differently-parsed object — an authz-drift hazard); the native backend also cannot honor the `ListAllTables` response-joining half |
| 7 | ~~`insert` emits **versionless** lineage~~ | insert bumps a Lance version | ✅ **fixed (GOAL 3)** — `insert` now reopens the dataset and stamps the real version on the WROTE edge, like update/delete |

## 2. vs Lakekeeper (Iceberg REST catalog)

> 🔄 **Currency check 2026-07-12** (cloned v0.13.1 + main@2026-07-11, CHANGELOG v0.12.0→HEAD read):
> the views/MVs genuinely-missing verdict below and "no lineage at all" REMAIN accurate; the
> multi-warehouse verdict is now STALE — it shipped 2026-07-15 (#3-A + #35). Framing changed
> materially: **Lakekeeper 0.13.0 (2026-06-30) now
> catalogs LANCE tables directly** via its Generic Table API (#1673): per-table credential vending,
> soft-delete/undrop, a dedicated OpenFGA object type with 16 per-action permissions, Console UI,
> and a pylakekeeper client. It is however **metadata-pointer-only by its own docs**
> (generic-tables.md): *no commit coordination, no schema enforcement*, no data plane (no
> insert/query/merge, no version/tag/branch ops, no schema evolution), statistics free-form
> informational — and still zero lineage. So "they do Iceberg, we do Lance → structurally N/A" is
> DEAD as a frame; the real position is: **Lakekeeper can now GOVERN Lance pointers; lance-ns
> OPERATES a Lance lakehouse** (full data plane §1 + versioned lineage + reconcile). Two phrasing
> softenings applied below per the same check: their OSS authz gained nested roles (+ Cedar in the
> paid tier), and their vending gained SSE-KMS + remote signing + Lance-table vending — so
> "vending ahead" is now "on par", and "ReBAC exceeds their roles" is toned to "finer-grained in
> the data path".

We govern a **Lance** lakehouse (single-writer directory namespace, immutable versions + native time-travel).
Many Iceberg-specific Lakekeeper features remain N/A — but see the currency note: Lance-pointer
governance itself no longer is.

| Capability | Us | Verdict |
|-----------|-----|---------|
| Multi-warehouse data plane | ✅ **SHIPPED (#3-A + #35, 2026-07-15):** admin API provisions a warehouse = one physically isolated bucket at runtime; `get_namespace` routes a bound namespace to its bucket; deactivate/activate lifecycle quarantines a tenant; real-resolver + live e2e coverage. | **Closed.** (Multi-tenant SaaS gap that this row previously called "genuinely missing" is now built. Remaining sub-item: multiple *storage profiles* per warehouse — still only matters at SaaS scale.) |
| Control-plane management API | Declarative config (env + Helm + FGA at boot); Lakekeeper-style **read-only maintenance mode** built. **Frontend control plane (Phase A, 2026-07-20):** grant/revoke (#72), index build/rebuild/drop (#73), the OpenFGA relationship-graph explorer (#81, beats the form-based OSS UIs), schema evolution (#74 — add SQL-expression column / rename / **re-type** (scalar Arrow target) / drop from the schema table, **table + per-column properties** (schema_metadata/update replaces the map; update_field_metadata merges per key), plus branch create/delete + tag delete/move from the refs row), a Lance-format badge + create-path rejection of format-selecting props (#78 — the one supported format is never a silent surprise), an admin audit-log viewer (#77 — `/audit` reads the #41 compliance trail from GreptimeDB's `opentelemetry_logs` via a session-gated BFF, filterable by action/outcome/subject/resource), **on-demand GC** (#75 — `POST /v1/table/{id}/maintenance/{preview,run}`: dry-run reclaimable versions honouring tag pins + retain-window + age cutoff, then reclaim), and **compaction control** (#76 — a per-table `target_rows_per_fragment` the sweep honours + `maintenance/compact` "compact now"), plus a **data-quality gate badge** (#82 — the table page reads the validator's latest `dataQualityAssertions` verdict from the dataset's producing runs via the lineage BFF and shows passed/blocked + check count, or an honest "no quality gate" when no run recorded one); all owner-gated, in the table view. | Was "missing but low-value"; the operator-facing surface is now built and at Lakekeeper/Unity-console parity |
| Soft-delete / undrop | `DeregisterTable` (`.lance-deregistered` marker) + `RestoreTable` + version time-travel | **Have — arguably stronger**; only a timed-expiration queue is N/A-by-design |
| User/role admin API | External OIDC (Dex) + OpenFGA tuples seeded on create + `.localbin/fga` | Missing *API*, not *capability* (our ReBAC is finer-grained IN THE DATA PATH; their OSS now has nested roles + admission gates, Cedar in the paid tier — 2026-07-12) |
| Task/job queue | Separate `compaction` service + Dapr/NATS JetStream | Reasonable split; a unified maintenance scheduler is missing |
| Storage-profile + credential vending | ModeB / Static / STS / **WebIdentity** with per-table session policies (`core/vending.py`) | **Have — on par** (2026-07-12: they added SSE-KMS vending + Iceberg remote signing + vending for Lance generic tables; we have no KMS/signing equivalent); multiple storage profiles missing (only matters with multi-warehouse) |
| Table / partition statistics | `GetTableStats` (Lance `total_bytes`/`num_rows`/fragment stats) + lineage `outputStatistics` | **Have (table)**; partition stats **N/A** — Lance clusters, doesn't partition |
| Views / materialized views | Endpoints exist → native 501 | **Genuinely missing + valuable**, but a **native-Lance gap** (`base_objects` is "reserved for future view deps"), not ours to fill yet. The medallion gold layer is our MV equivalent today. |

| **Lance table support** (NEW row, 2026-07-12) | full data plane (§1): Arrow-IPC write/query, versions/tags/branches, schema evolution, blob-v2, commit-level lineage + storage reconcile | **Lakekeeper 0.13 governs Lance as METADATA POINTERS only** (vending + soft-delete + FGA + UI; explicitly no commit coordination / schema enforcement / data plane). Complementary more than competitive today — and a possible future interop: registering our tables as their generic pointers would give a shared org catalog without ceding the data plane. |

**Net (updated 2026-07-15):** multi-warehouse is now **SHIPPED** (#3-A + #35). The only remaining
genuinely-missing-and-valuable catalog item is **working views/MVs (blocked on native Lance)**; multi-storage-profile
matters only at multi-tenant-SaaS scale. Everything else is present-or-better or N/A-by-design. Lakekeeper still has
**no lineage at all** — and its Lance support is governance-of-pointers, not operation-of-a-lakehouse.

## 3. vs Marquez (OpenLineage reference server)

We ingest OpenLineage into Apache AGE with version/schema/columnLineage/dataSource/tags/outputStatistics/
dataQualityAssertions facets. We are **at or above Marquez** on the high-value axes.

| Capability | Us | Verdict |
|-----------|-----|---------|
| Run-state lifecycle (START…FAIL/ABORT) | `(:Run)` folds lifecycle; `/runs` shows state+progress+error; custom `progress` facet Marquez lacks | **On par** |
| Dataset versioning | `WROTE` edge carries the **real Lance version** (not a synthetic UUID), storage-cross-checkable | **Exceeds** |
| Column-level lineage | field-to-field `DERIVED_FROM_COLUMN` + transformation kind + **`masking`** bit, FGA-gated | **On par or better** |
| Dataset schema history | per-version schema on the `WROTE` edge; `/schema?version=N` | **On par** |
| Job versioning | `MERGE (:Job)` only, no JobVersion nodes | Missing, low value (fixed medallion jobs) |
| Job source-code / context (`sourceCodeLocation`/`sql`) | `sourceCodeLocation` **now ingested** as a GOAL 3 here-dummy (git repo + path, on `Job.source_location`) | Partly there — the *auto-derived* value (rask runner's git + pipeline) lands with lance-ray (GOAL 3-real); `sql` still N/A (no SQL engine) |
| Full standard facet set | high-value ones present | Missing & worth adding: `parent` (run hierarchies), `dataQualityMetrics` (column null/distinct/min-max); low-value: `nominalTime`, `processing_engine`, `symlinks`, `storage`, `inputStatistics` |
| Search / list / namespaces API | ✅ **list shipped (GOAL 4 A1/A2)** — governed `GET /datasets` (`?namespace=`/`?tag=` + pagination), `/jobs`, `/namespaces`; the frontend Browse landing renders them. Tier-1 governed metadata **/search shipped 2026-07-11** (substring over names/namespaces/tags/columns, FGA-filtered); only tier-2 FTS/**vector search** still deferred (reuses rask's Lance FTS/vector) | On par for *browse + basic search*; semantic search deferred to the query-engine phase |
| SQL-parse-based lineage | rely on producers emitting `columnLineage` | **N/A** (no SQL engine); minor: could derive edges from `add_columns`/`update` SQL |
| Backfill detection | Lance `add_columns` recorded as versioned WROTE; not *classified* as backfill | Low value (no partitions) |
| Graph UI | ✅ **shipped (GOAL 3)** — the SvelteKit Svelte-Flow explorer at `/lineage` + `/` (`$lib/LineageExplorer.svelte`): Datasets/Jobs/Columns planes, click-node → upstream/downstream/producers + column-lineage panel | On par — a production graph explorer now exists |

**Moats over Marquez** (it structurally cannot do these): **storage-version reconcile** (`in_sync`/`storage_ahead`/
`graph_ahead` vs the on-disk Lance version — plus a periodic **back-fill** of writes whose lineage event was
lost, GOAL 4 B4), **FGA-governed reads** (per-object authz + transitive-disclosure
filtering + read-audit), **verified creator** (OIDC `sub` stamped, not self-asserted), **durable idempotent
at-least-once ingest** (Dapr/JetStream + MERGE-on-run_id + natural-key dedup).

**Net:** genuinely-missing-and-valuable = (a) job-context facets + job versioning, (b) a search/list/namespaces
discovery API (✅ list + tier-1 search shipped) + tag management (✅ **shipped #49, 2026-07-16** — governed
tag/description writes with attribution; producer facet tags union with curated ones), (c) run `parent`
facet, (d) `dataQualityMetrics`, (e) a production graph UI, (f) the versioned-insert lineage gap (§1 #7).
N/A-by-design: SQL-parse lineage, partition-backfill.

## Recommended next (by value)
**Shipped since this was written (GOAL 3):** ✅ versioned-insert lineage (§1 #7 — `insert` now stamps the
real version), ✅ `sourceCodeLocation` job-context facet as a here-dummy (rask's runner auto-derives the real
one later), ✅ production graph UI (the SvelteKit explorer at `/lineage` + `/`, `$lib/LineageExplorer.svelte`
with the upstream/downstream/producers/column-lineage detail panel).

**Also shipped (GOAL 4):** ✅ discovery *list* API (`/datasets`, `/jobs`, `/namespaces`, governed + filtered)
+ the Browse landing; ✅ a truly event-driven cascade head (lance-ray subscribes to the raw-write event);
✅ storage→graph reconciliation **back-fill** for dropped writes; ✅ compute-on + quality-gate chart toggles.

Remaining, by value:
1. **Semantic search** (`/search?q=`) — the *list* API now covers browse; typo-tolerant/vector search reuses
   rask's Lance FTS+vector and lands with the query-engine phase. Defer.
2. **`dataQualityMetrics`** — column null/distinct/min-max; costly on Lance (stats live outside the file). Low.
3. **Job-context auto-instrumentation** — the *real* `sourceCodeLocation` + run `parent` facets, emitted from
   rask's runner when lance-ray OpenLineage lands (GOAL 3-real). Supersedes the here-dummy.
4. ✅ **Multi-warehouse routing — SHIPPED (#3-A + #35).** Working views/MVs remain **only when** native Lance
   view deps (`base_objects`) arrive.
