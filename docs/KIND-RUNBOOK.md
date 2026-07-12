# Kind live-verification runbook — every pending 🟡, one pass, copy-paste order

**Written 2026-07-11.** Everything below is CODE-COMPLETE and CI-proven (unit + render tiers);
this pass turns the remaining 🟡 items in `todo_fable.md` §7a into ✅. Each step says the command
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
2. `--set security.serviceAccounts.enabled=true` → all pods Ready AND `dapr mtls -k` still
   verifies (the audit's pre-flip gate — the injector's projected token must be untouched).
3. `--set security.infraContexts.enabled=true` → infra pods Ready; `kubectl rollout restart` on
   rustfs/age/openbao → data intact after restart (the fsGroup proof; wrong uid = CrashLoop or
   permission errors, fix via `security.infraContexts.<comp>.runAsUser` values).
4. ONLY then: `kubectl label ns <ns> pod-security.kubernetes.io/enforce=baseline` (soak) →
   `=restricted` — the wait-age init containers are now compliant, so nothing should be rejected.

## 7 · Chart values passthrough for train (optional tidy)

The train defaults all work; if you want them values-wired:
`medallion.train.{topic,entrypoint,trainerIdentity,modelsNamespace,lineageUrl}` → env in
`medallion.yaml`, then `helm template | grep MEDALLION_TRAIN` before upgrading. Also set
`vending.externalBlobBases` to include `s3://<bucket>/models/` (the #92 allowlist for model
pointers).

## Reporting back

Paste failures verbatim (pod logs + the failed assertion). Anything red here jumps the work
queue ahead of new features.
