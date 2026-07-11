# Operators & the submit-seam boundary — what we adopt, what rask supplies, what we never build

**Status: DECIDED 2026-07-11** (user question: "what is the most logical operator for this platform,
and can rask help"). Grounded in [`RASK-INTEGRATION.md`](RASK-INTEGRATION.md) (rask's actual chart),
[`RAY-TRAIN.md`](RAY-TRAIN.md) D6, and [`RAY.md`](RAY.md). One-line answer: **KubeRay first — and
rask helps with everything, because rask already operates every operator on the list.** The merge
is "flip values at rask's operators", never "deploy operators ourselves".

## 1 · Adoption order (most logical first)

| # | Operator | Replaces (ours, hand-rolled) | Why this rank |
|---|---|---|---|
| 1 | **KubeRay + Kueue** | raw Ray head Deployment + our submit/re-attach/poll logic | Replaces the WEAKEST thing we own. A `RayJob` CR is the missing *lifecycle owner* the whole TRAIN design (D2 submit-and-ack) works around: the operator watches the job to a terminal state, owns retry policy + TTL cleanup; `RayService` gives rolling cluster upgrades; Kueue adds GPU quota + gang scheduling for training. Already pinned as the rask-merge step (D6). |
| 2 | **CloudNativePG** | hand-rolled AGE StatefulSet + OpenFGA datastore | Managed Postgres `Cluster` (HA, backups, failover) for the ONLY relational state of record (AGE + OpenFGA). ⚠️ Gated by the AGE-extension decision (stock CNPG images lack AGE): custom image vs separate operand vs Lance-native graph — `RASK-INTEGRATION.md` §Open decisions. |
| 3 | **rustfs-operator** | hand-rolled RustFS Deployment | S3 `Tenant` CR with a declarative `buckets:` list — our lakehouse + observability buckets become list entries. |
| 4 | **NACK** (NATS operator) — *optional* | the imperative `nats-stream-job.yaml` provision Job | Declarative `Stream` CRDs would replace the shell Job that today creates `LINEAGE` / `MEDALLION` / `TRAINING` (Dapr's jetstream component does not auto-create streams). Nice-to-have: the Job works and is idempotent; NACK removes a boot-ordering foot-gun, nothing more. |

**What we never build: a custom lance-ns operator.** An operator earns its complexity when state of
record lives in CRDs and needs reconciling. Ours does not: catalog/lakehouse state lives in **Lance
manifests on S3**, authz + lineage in **Postgres** (OpenFGA, AGE), and every control loop we need is
either an existing service (compaction sweeper), an existing Job (stream/bucket/seed provisioning),
or one of the operators above. A "lance operator" would be a second reconciler over state that
already has an owner.

## 2 · How rask helps (short version: with all of it)

rask **already operates every operator above** — KubeRay, Kueue, CloudNativePG, rustfs-operator —
plus NATS, Dapr, OpenFGA-server, Traefik, and the GreptimeDB observability stack
(`RASK-INTEGRATION.md` §Pre-flight). So the adoption plan is NOT "install operators here"; it is the
merge itself: flip `age.enabled`/`rustfs.enabled` off, point the externalization values at
`<release>-postgres-rw` / the rustfs `Tenant`, and retire the raw Ray head into rask's KubeRay
cluster. In exchange we contribute what rask lacks entirely: lineage, actual OpenFGA *enforcement*
(rask provisions the server but wires nothing to it), and the event-driven medallion estate.
Interim posture in THIS repo: keep the hand-rolled infra — it is demo-tier scaffolding that the
merge deletes (`RASK-INTEGRATION.md` §5), so operator-izing it here would be double work.

## 3 · The Ray submit seam: lance-ns is the agnostic side (DECIDED, mirrors D6)

Question: does the Ray-submit belong in rask or in lance-ns — which is more agnostic for the jobs
we submit? **Ours, deliberately:**

- `services/medallion/services/ray_submit.py` is **httpx-only against the Ray Jobs REST API** — no
  `ray` package, no Kubernetes API, no KubeRay CRDs. Its whole contract is *entrypoint + env + a
  deterministic submission id*. That runs unchanged against a raw Ray head on kind, a KubeRay
  `RayCluster`/`RayService`, or a managed Ray — anything speaking the Jobs API.
- The jobs themselves (`ray_lance_job.py`, `ray_stage_job.py`, `ray_train_job.py`) are equally
  agnostic: plain env-driven scripts baked into the ray image, zero submission-side coupling.
- rask's path (`ray-kit`/orchestrator → Kueue-admitted `RayJob` CRs) is the more *operationally
  capable* transport — and the more coupled one (Kubernetes API + KubeRay + Kueue present).

So the roles split, and the split IS the design (RAY-TRAIN.md D6):

- **lance-ns owns the seam + the contracts**: trigger payloads, the deterministic idempotency key
  (`ray-<stage|train>-<token>`), the lineage contract, the FGA gates. These survive the merge
  untouched.
- **rask owns the production transport**: at the merge, add a second transport behind the SAME
  `submit_stage_job`/`submit_train_job` signatures that creates a `RayJob` CR instead of POSTing
  `/api/jobs/`. Idempotency maps 1:1 — use the deterministic submission id as the **CR name**;
  "create of an already-existing CR" becomes the re-attach branch.
- Anti-goals: do NOT port our submit logic into rask, and do NOT adopt ray-kit here. The seam is
  the boundary; it is already in the right repo.

## 4 · Do Dapr or Lance need an operator story? (asked 2026-07-11)

**Dapr — already covered, nothing to adopt.** Dapr's control plane *is* an operator
(`dapr-operator`, sidecar-injector, placement, sentry — helm-installed here, already running on
rask), and our pub/sub wiring is already declarative: `Component` CRs (`pubsub.jetstream`), a
`Subscription`-via-code model, and per-app scoping. The one imperative residue is stream
provisioning — that is the NACK row above, not a Dapr gap. Also pinned (python-infrastructure
skill + #115 review): **Dapr Workflow stays un-adopted** — every multi-step path we have
(bytes-then-commit registration, stage hops) is token-keyed idempotent, so JetStream's
redeliver-the-whole-message model suffices; a workflow engine would add a sidecar state store
dependency for crash-recovery semantics we already get from idempotency keys.

**Lance — no operator exists, none is missing.** Lance is a format + libraries; its "control
plane" is the manifest on S3, and CAS commits are the reconciler. The operator-shaped concerns it
DOES have are already owned elsewhere:

| Concern | Owner today | Status |
|---|---|---|
| background maintenance (compact/optimize) | `services/compaction` sweeper (cron-driven, FAIL-visible) | shipped |
| orphan-artifact GC (`models/<m>/<token>/` from crashed runs; blob-pointer lifecycle) | future janitor keyed on registry-referenced tokens | §9 open item — **the one real gap**; becomes more load-bearing as models multiply |
| stream/bucket/grant provisioning | chart Jobs + seed scripts (idempotent) | shipped; NACK could absorb the stream half |
| version/feature pinning (`pylance`, `lance-ray`, data_storage_version) | image pins + probe-before-callsite (§0) + docs/RAY.md landmines | process, not software |

So: nothing to install for either. The single actionable follow-up either way is the **orphan
janitor** (already tracked in todo_fable §9 as blob-pointer lifecycle — GC must never collect
registry-referenced artifact objects, and crashed-run tokens need a sweep).
