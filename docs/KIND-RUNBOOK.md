# Kind live-verification runbook — every pending 🟡, one pass, copy-paste order

**Written 2026-07-11.** Everything below is CODE-COMPLETE and CI-proven (unit + render tiers);
this pass turns the remaining 🟡 items in `docs/GOAL-prove-it.md` into ✅. Each step says the command
AND the assertion — if an assertion fails, stop and report; that failure jumps the work queue.

## 0 · Rebuild + roll (prerequisite for everything)

```bash
make build            # or your image-build path — catalog/lineage image + the medallion image
docker build $(BUILD_ARGS) -f .docker/ray-lance.dockerfile -t ray-lance:dev .   # NOW BAKES ray_train_job.py
kind load docker-image <the images> --name <cluster>
helm upgrade --install lance-ns ./chart --timeout 240s
```
**ASSERT:** all pods Ready; `kubectl logs job/<release>-nats-stream-*` shows the **TRAINING** stream
created next to LINEAGE/MEDALLION (new — without it every `/train` publish 503s).

## 1 · The two e2e suites (the §0 done-done gate)

```bash
make e2e-governed-union     # kind union stack: governed cascade + writer-gate deny sub-phases
make e2e-lineage            # real AGE via Dagger — includes the NEW terminal-lifecycle/column-GC test
```
**ASSERT:** both green. (CI already runs the lineage one — a local pass additionally proves your
cluster's AGE, not Dagger's.)

## 2 · Compaction failure visibility

Fault-inject once: delete ONE data file under a dataset's manifest on RustFS, wait ≥2 cron ticks.
**ASSERT:** exactly ONE FAIL Run node for it in `/runs` + `/events` (deterministic
`compaction-fail-<id>` run id = no flood), and the sweep keeps processing other datasets.

## 3 · Merge-insert index hook

One real `POST /v1/table/<id>/merge_insert` (catalog image must be rolled).
**ASSERT:** a BTREE index on the merge key appears (`/indices` or `describe_indices`), the
documented extra version bump occurs, and a second merge_insert does NOT re-create the index.

## 3b · Blob serving path (Batch 13 — catalog image must be rolled)

Against the media table the cascade already wrote (`bronze-media$objects`, blob column `payload`):

```bash
curl -sS -D- -o /tmp/full.bin "http://localhost:8000/v1/table/bronze-media\$objects/blobs?column=payload&row=0"
curl -sS -D- -o /tmp/win.bin -H "Range: bytes=0-3" \
  "http://localhost:8000/v1/table/bronze-media\$objects/blobs?column=payload&row=0"
```
**ASSERT:** first response is `200` with `Accept-Ranges: bytes` and `/tmp/full.bin` is a valid PNG
(`file /tmp/full.bin`); second is `206` with `Content-Range: bytes 0-3/<size>` and `/tmp/win.bin` is
exactly the 4-byte PNG magic prefix (`\x89PNG`). With FGA on, a principal WITHOUT `can_read_data` on
the table gets `403` on the same URL (reader tier, same rung as `/query`).

## 3c · Data-contract clauses (Batch 21 — declared columns + freshness)

The demo movers now DECLARE consumer dependencies (`requiredColumns` in values: `id` on the tabular
stages; `id,thumbnail,embedding` on media-to-silver). After one cascade run:
```bash
curl -s http://localhost:8001/runs | python3 -m json.tool | grep -A3 column_declared | head
```
**ASSERT:** the silver/gold runs' `quality_assertions` contain `column_declared` entries with
`success: true` per declared column. NEGATIVE (the breaking-change detector): `--set` a bogus
declaration on one mover (e.g. `requiredColumns: "ghost"`), re-fire the cascade — that stage's run
shows `column_declared success:false column:ghost`, `quality_passed:false`, and the NEXT stage never
runs (promotion blocked, cascade halted at the violation). Revert after.

Freshness: `helm upgrade --reuse-values --set services.lineage.freshnessBudgetHours=0.01` (36s),
wait ≥1 min without producing, then:
```bash
curl -s "http://localhost:8001/datasets/gold\$catalog/reconcile" | python3 -m json.tool
```
**ASSERT:** `"stale": true` while `"in_sync": true` (its own axis), and the next cron tick WARNs
`lineage_reconcile_stale` with the dataset list. Revert the budget to 0 (axis off).

## 4 · The train drive (#115, end to end)

```bash
OPENFGA_API_URL=http://localhost:8081 scripts/seed_medallion_fga.sh    # re-run: trainer grants
curl -X POST <lance-ray>/train -H 'dapr-api-token: …' -H 'content-type: application/json' \
  -d '{"model":"churn","features":[{"dataset":"silver$features"}]}'
```
**ASSERT, in order:**
1. `202 {token}`; the trainer consumer logs `train_job_dispatched` (deny-test: revoke
   `user:service-trainer reader namespace:silver` → next POST's trigger is DROPped with
   `train_denied`, NO Ray job appears; restore the grant after).
2. `/runs` shows `train.churn` START → RUNNING(progress) → COMPLETE.
3. `upstream(models$churn)` lists the feature datasets WITH their pinned versions.
4. A serving-shaped read loads `weights.json` from the PLAIN S3 path (`aws s3 cp
   s3://<bucket>/models/churn/<token>/weights.json -`) — no Lance reader involved.
5. Redelivery safety: `kubectl delete pod <producer>` mid-run or re-publish the same trigger →
   mover logs `ray_train_job_reattach`, NO second Ray job, NO duplicate registry version.
6. FAIL path: POST with a nonsense pinned version (e.g. `"version": 9999`) → a FAILed run with a
   VERSIONLESS output in `/runs`, registry version count unchanged.

## 5 · The janitor (AFTER step 4's FAIL injection — it made a real orphan)

```bash
uv run python scripts/model_artifact_janitor.py \
  --registry-uri s3://<bucket>/medallion/models/churn --artifact-base s3://<bucket>/models/churn \
  --s3-endpoint http://localhost:9100 --s3-key … --s3-secret … --ttl-hours 0
```
**ASSERT:** dry-run report lists the FAILed run's token under `candidates` and every published
token under `kept_referenced`; nothing was deleted. ONLY THEN re-run with `--delete` once and
assert the orphan dir is gone and the published artifacts still load (step 4.4 re-check).

## 6 · Security flips (needs a POLICY-ENFORCING CNI — Calico/Cilium; kind's default silently
## ignores NetworkPolicy, so on plain kind only steps 6.2–6.4 are provable)

In the audit's order, one flag at a time, re-asserting pods Ready after each:
1. `--set networkPolicy.enabled=true` → e2e suites still green; **NEGATIVE probe:**
   `kubectl exec deploy/lance-ns-web -- wget -T3 -qO- http://lance-ns-openbao:8200/v1/sys/health`
   **times out** (openbao is exclusive), while the catalog still consumes secrets at boot
   (positive control). ESO users: set `networkPolicy.openbaoExtraFrom` FIRST.
2. ✅ **PROVEN 2026-07-13** — `--set security.serviceAccounts.enabled=true` → all pods Ready, each
   bound to `lance-ns-sa-<workload>`, the k8s-API token still NOT mounted (the audit's intent), daprd
   reports zero component failures, and `POST /produce` still cascades.
   > This flip was **unshippable before that date**: it CrashLooped every Dapr-injected pod. daprd
   > auto-registers a built-in `kubernetes` secret store and initialises it from the SA token that
   > `automountServiceAccountToken: false` removes → `[INIT_COMPONENT_FAILURE] secretstores.kubernetes/v1`
   > → fatal. Fixed by disabling the unused store (`dapr.io/disable-builtin-k8s-secret-store`, now on
   > every Dapr workload) — which keeps the no-mounted-JWT intent instead of walking it back.
3. ✅ **PROVEN 2026-07-13** — `--set security.infraContexts.enabled=true` → infra pods Ready under
   non-root (age uid 999, rustfs uid 1000, `runAsNonRoot: true`); `kubectl rollout restart` on
   age + rustfs → **data intact**: 441 AGE Run nodes and 392 RustFS objects before and after (the
   fsGroup proof; a wrong uid = CrashLoop or permission errors → fix via
   `security.infraContexts.<comp>.runAsUser`).
4. ⛔ **PSA `restricted` is NOT achievable today — the old claim here ("nothing should be rejected")
   was wrong** (disproven live 2026-07-13). `enforce=restricted` **blocks pod creation**:
   ```
   pods "lance-ns-catalog-…" is forbidden: violates PodSecurity "restricted:latest":
     unrestricted capabilities (container "daprd" must set securityContext.capabilities.drop=["ALL"]),
     seccompProfile (pod or container "daprd" must set securityContext.seccompProfile.type to "RuntimeDefault")
   ```
   Two independent blockers; the chart now owns the fixable one:
   - **App containers — already `restricted`-clean** (correction to the old text): `lance.securityContext`
     sets `runAsNonRoot` + `allowPrivilegeEscalation:false` + `capabilities.drop:[ALL]` +
     `seccompProfile:RuntimeDefault` on every app container. They were never the blocker.
   - **The Dapr-injected `daprd` sidecar — NOW FIXABLE via the chart** (added 2026-07-13, gated + OFF by
     default like `networkPolicy.enabled`). Set both together:
     `--set dapr.sidecarRestricted=true --set dapr.dapr_sidecar_injector.sidecarDropALLCapabilities=true`
     → the first adds the `dapr.io/sidecar-seccomp-profile-type: RuntimeDefault` annotation on all 9 Dapr
     workloads (render-asserted), the second flips the injector env `SIDECAR_DROP_ALL_CAPABILITIES=true`
     so injected sidecars carry `drop:[ALL]`. NOTE this re-rolls the Dapr control plane + every injected
     pod — a prod-values change, not driven on kind (same treatment as L3 NetworkPolicy).
   - **The OTel Collector — a STRUCTURAL blocker no value fixes.** It's a single Deployment whose `filelog`
     receiver inherently mounts hostPath `/var/log/pods` (to tail the infra pods), which `restricted` (and
     even `baseline`) forbids. Full-namespace enforce is therefore impossible while the Collector shares the
     namespace: give it its OWN namespace at `baseline`, or add a `ServiceAccount` PSA exemption in the
     API-server admission config. This is why full enforce stays **parked-by-design**, like L3 — the chart
     hardens what it owns; the cluster-policy exemption for the Collector is a deploy decision outside the
     app chart.

   **Current end state (safe):** the namespace carries `warn=baseline` + `audit=baseline` — full
   visibility, no admission blocking. Promote to `enforce` only after the Dapr flags are set AND the OTel
   Collector is exempted per the bullet above.

## 6.5 · Dapr resiliency + DLQ (Batch 18 — DEFAULT ON; verify the deployed default)

Nothing to flip — the layer ships enabled (the durable-consumer question was answered from the
component source: consumer names scope per stream, the dlq.* topics live on their own DLQ stream).
After `helm upgrade` + a rollout restart of the subscriber pods:

**ASSERT (in order):**
1. `kubectl get resiliency` shows `<release>-pubsub-resiliency`; subscriber pods carry `*_DLQ_TOPIC`
   envs; `nats stream ls` shows the `DLQ` stream (subjects `dlq.>`) alongside
   LINEAGE/MEDALLION/TRAINING.
2. Sanity (expected-pass): main durable consumers re-attach after restart with no
   "consumer name already in use" errors — per-stream consumer scoping proven live.
   **Caveat (observed 2026-07-13): on an UPGRADED cluster whose durables predate a
   consumer-config change** (this batch changes maxDeliver/backOff), those errors ARE expected
   transiently — durables are create-once, so sidecars retry-loop until JetStream reaps the old
   ones at their inactive threshold (~20–25 min; or `nats consumer rm` the `<app>-durable`
   consumers on LINEAGE/MEDALLION/TRAINING/DLQ for an instant cutover). The assert holds on a
   fresh install, or on an upgraded one only after the reap/rm. See RESILIENCE.md gap #7.
3. Poison-inject: publish a stage trigger with a bogus payload the mover always RETRYs (or scale AGE
   to 0 and fire one event). Watch the sidecar retry ~5 times over ~7.5 min, then the app's
   `/dlq-event` log shows `dapr_dead_letter_parked` (ERROR) with the token — the message is PARKED,
   not silently gone, and the cascade continues for other messages. A malformed payload the handler
   DROPs (rather than RETRYs) parks immediately — same destination, no retry wait.

   > ⚠️ **`kubectl logs` will NOT show it — that is not a failure.** The services run under
   > `opentelemetry-instrument` with `OTEL_LOGS_EXPORTER=otlp`, so the auto-instrumentation attaches
   > an OTLP handler to the ROOT logger and every app log record ships to **GreptimeDB** instead of
   > stdout; `kubectl logs` carries only uvicorn's access lines (plus the sidecar's own output). This
   > is the OTLP log-export design working as intended, but it makes every "the app logs X" assert in this
   > runbook a Greptime query. Verified 2026-07-13 (port-forward greptime 4000):
   > ```bash
   > curl -s "http://localhost:4000/v1/sql?db=public" --data-urlencode \
   >   "sql=SELECT timestamp, severity_text, body FROM opentelemetry_logs \
   >        WHERE body = 'dapr_dead_letter_parked' ORDER BY timestamp DESC LIMIT 5"
   > ```
   > (The same applies to `train_denied`, `train_trigger_malformed`, `ray_train_job_reattach`, the
   > compaction emit warnings — all present in `opentelemetry_logs`, none in `kubectl logs`.)
4. Normal traffic still flows: `make e2e-medallion` green on the default values.
5. Escape hatch (optional): `--set dapr.resiliency.enabled=false` restores the exact pre-existing
   broker-only redelivery (30-300s backOff, no DLQ) — the chaos-verified baseline.

## 7 · Chart values passthrough for train (optional tidy)

The train defaults all work; if you want them values-wired:
`medallion.train.{topic,entrypoint,trainerIdentity,modelsNamespace,lineageUrl}` → env in
`medallion.yaml`, then `helm template | grep MEDALLION_TRAIN` before upgrading. Also set
`vending.externalBlobBases` to include `s3://<bucket>/models/` (the #92 allowlist for model
pointers).

## Reporting back

Paste failures verbatim (pod logs + the failed assertion). Anything red here jumps the work
queue ahead of new features.
