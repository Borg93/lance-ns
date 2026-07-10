# Real Ray-cluster compute seam

The medallion cascade's in-process compute (`services/medallion/services/compute.py`) is the **fake-Ray**
placeholder — a synchronous `lance.write_dataset` that stands in for a distributed Ray Data job so the
event-driven loop is testable without a cluster. This doc covers the **real** thing: an actual Ray cluster in
kind + `ray job submit`, proving Lance's distributed capabilities against RustFS. Production is KubeRay (a
`RayCluster` CR) via the rask merge; this is the raw-cluster proof that the seam is real, not fake.

> Everything here is the Ray **DATA** shape (bounded stage transforms). The Ray **TRAIN** shape —
> long-running training jobs, model-as-Lance-dataset, `jobType=TRAINING` lineage — is a separate,
> decided design: see [`docs/RAY-TRAIN.md`](RAY-TRAIN.md) (task #115).

## What runs

| Piece | File |
| ----- | ---- |
| Thin CPU Ray image (`rayproject/ray:2.56.0-py312-cpu` + `lance-ray` + `pylance==8.0.0`) | `.docker/ray-lance.dockerfile` |
| A real Ray head (GCS 6379, dashboard/job API 8265) + Service, single node | `deploy/ray-lance-demo.yaml` |
| The submitted job — a genuine distributed Lance pipeline | `scripts/ray_lance_job.py` |
| One-shot driver | `make ray-demo` (and `make ray-demo-clean`) |

`make ray-demo` builds + `kind load`s the image (`make ray-image`), applies the head, waits for it, then
`ray job submit`s `ray_lance_job.py` (baked into the image at `/home/ray/jobs/`), passing a per-run `RUN`
via `--runtime-env-json` (exec-level env is NOT propagated to a Ray job). The job reads/writes
`s3://lance-catalog/ray-<run>/…` on the in-cluster RustFS. Tear down with `make ray-demo-clean`.

## What it proves (live, one job, four capabilities)

```
[1/4] WRITE   ok  fragments=4  dsv=2.2  stable_row_ids=True   # distributed append into a stable-row-id dataset
[2/4] INDEX   ok  indices=['id_idx']  query(id=7)->1 row
[3/4] EVOLVE  ok  [id,v,doubled] → [id,v,doubled,tripled]  v→v+1  (old version still pins the old schema)
[4/4] COMPACT ok  fragments 4->2                # compact_files merges the small fragments
RAY-LANCE ALL OK
```

- **Distributed WRITE + stable row ids** — `lance_ray.write_lance` has no `enable_stable_row_ids` param, so we
  create `dst` with stable ids (an empty table of the output schema) and then distributed-**append** the Ray
  fragments into it (`mode="append"`, `min_rows_per_file<max` → 4 fragments in parallel + one commit).
  Stable-row-ids is a dataset-level property, so the appended rows inherit it — `has_stable_row_ids=True`.
- **DATA EVOLUTION** — `lance_ray.add_columns` distributively adds `tripled = v*3`; the schema and version
  advance, and time-travel to the pre-evolution version still shows the old schema (immutable versions).
- **COMPACTION** — `lance_ray.compact_files(CompactionOptions(target_rows_per_fragment=…))` merges 4 → 2
  fragments.

## Verified lance_ray ↔ pylance version findings (grounded in reality, not just docs)

Two real incompatibilities surfaced (and are handled) — worth knowing before the rask merge pins versions:

1. **Ray Data's built-in `write_lance` datasink** calls `write_fragments(storage_options_provider=…)`, a kwarg
   pylance 8.0.0 lacks → use the **`lance-ray` package** (`lance_ray.write_lance`), which is version-matched.
2. **lance_ray's DISTRIBUTED index build is incompatible with pylance 8.0.0 — both paths, verified.** The
   scalar path (`create_scalar_index`) calls `create_index_uncommitted(index_type=, fragment_ids=)` and the
   vector path (`create_index`, IVF_FLAT/IVF_PQ) calls `create_index_segment_builder` — pylance 8.0.0 exposes
   *neither* of those distributed-index primitives. And *unpinning* pylance breaks `write_dataset(min_rows_per_file=)`.
   So on our pinned pylance the demo builds the index with the dataset's **native** pylance API inside the ray
   job (a real index a query serves — the `index created via ray + a query uses it` contract). A truly
   worker-distributed index needs the lance_ray↔pylance version alignment the rask/KubeRay merge will pin.
3. `lance_ray.write_lance` has **no `enable_stable_row_ids`** param. Work around it by creating the target
   with stable ids (a native pylance `write_dataset(enable_stable_row_ids=True)` of an empty schema) and then
   distributed-**appending** the Ray fragments — the property is dataset-level, so the output ends up with
   `has_stable_row_ids=True`.
4. `compact_files` needs a real `CompactionOptions` on pylance 8 — a bare `None` trips an internal dict check.

## Event-driven cascade integration (wired, not just a demo)

The medallion movers can run their stage compute as a real `ray job submit` **in response to their Dapr/NATS
cascade trigger** — gated behind `medallion.ray` (default off; requires `medallion.compute` + a running Ray
cluster). Fake-Ray in-process stays the default.

- **Flag:** `MEDALLION_RAY_ENABLED` (+ `MEDALLION_RAY_ADDRESS`, default `http://ray-lance-head:8265`),
  chart value `medallion.ray`.
- **Submit path:** `services/medallion/services/ray_submit.py` — the mover POSTs to the **Ray Jobs REST API**
  (`/api/jobs/`) with `httpx` (no `ray` package in the mover image), passing `FROM_URI/TO_URI/STAGE` + S3
  creds as `runtime_env` env-vars, then polls `GET /api/jobs/{id}` under an `asyncio.timeout`. On success the
  mover `measure()`s the written dataset so the OpenLineage WROTE edge is **identical** to the in-process
  path; on failure/timeout it raises → the mover returns RETRY and Dapr redelivers (the job is
  overwrite-idempotent).
- **The job:** `scripts/ray_stage_job.py` (baked in the image) reads upstream, stamps the `stage` column
  across Ray workers, and writes downstream at 2.2 + stable row ids (clears the dir first, since
  `enable_stable_row_ids` is create-time-only and the cascade reuses the stage URI under overwrite semantics).

**Live-proven on kind:** `/produce` → the `raw-to-bronze` mover (ray on) submitted a Ray job that produced
`bronze` (`stage=bronze`, 2.2, `stable_row_ids=True`), and AGE shows `bronze$events` DERIVED_FROM `raw_events`
with the real measured stats. With the flag off, `make e2e-medallion` (fake-Ray path) still passes.

## Relationship to the cascade

This is the production shape of the `compute.py` seam: `read → transform → write → version` becomes a real
`ray job submit` instead of an in-process call. It also directly answers the "cascade doesn't parallelize"
limitation — Lance *does* parallelize writes (fragment-parallel + single commit); our in-process
`mode="overwrite"` was the placeholder, not a Lance limit. The mover-submits-Ray-jobs wiring above is done;
the **KubeRay operator** (a `RayCluster` CR) replacing the raw Ray head is the rask-merge step.
