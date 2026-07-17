#!/usr/bin/env bash
# Render the PRODUCTION overlay (values-prod.yaml) and assert its HA + security switches are actually ON.
# Nothing else in CI renders the prod overlay — the e2e jobs deploy the DEFAULT (kind) values — so without
# this a regression that silently ships the dev posture in prod (NetworkPolicy off, OpenFGA/Dapr single-
# replica) sails through green. Dummy values satisfy the render-FAILS-CLOSED prod-secret guards (appToken /
# edgeAuth htpasswd / age pw / rustfs key); supplying them ALSO proves the guards don't block a legitimate
# prod render. Run: `make prod-render-check` (or in CI). Requires helm + the vendored chart/charts/*.tgz.
set -euo pipefail

CHART="${CHART:-chart}"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

helm template lance-ns "$CHART" -f "$CHART/values-prod.yaml" \
  --set image.catalog.tag=v0 --set image.web.tag=v0 \
  --set dapr.appToken=ci-dummy-token-0000000000 \
  --set 'observability.edgeAuth.htpasswd=observer:$apr1$ci000000$0000000000000000000000' \
  --set age.password=ci-dummy-pw --set rustfs.secretKey=ci-dummy-key \
  --set backups.volumeSnapshot.snapshotClassName=csi-snapclass \
  --set ingress.host=lance.example.com > "$OUT"

fail() { echo "!! prod-render-check: $*" >&2; exit 1; }

# 1. Network isolation ON (the audit's headline gap): default-deny + DNS + the exclusive openbao lock.
np=$(grep -c "kind: NetworkPolicy" "$OUT" || true)
[ "$np" -ge 9 ] || fail "prod must render the network-isolation layer (>=9 NetworkPolicies), got $np"
grep -q "default-deny" "$OUT" || fail "prod NetworkPolicy set missing default-deny"
grep -q -- "-openbao" "$OUT" || fail "prod NetworkPolicy set missing the openbao ingress lock"

# 2. OpenFGA HA — the authz chokepoint every governed call fails-closed through: 3 replicas. (The subchart
# Deployment's spec.replicas renders ~10 lines below its metadata.name; only the Deployment carries a
# replicas: field, so the windowed grep can't false-match the Service/SA/migrate-Job of the same name.)
grep -A15 "name: lance-ns-openfga$" "$OUT" | grep -q "replicas: 3" \
  || fail "prod OpenFGA must run 3 replicas (authz SPOF)"

# 3. Dapr control-plane HA — Sentry is the mTLS CA in the sidecar cert-renewal path.
awk '/name: dapr-sentry$/{n=1} n&&/replicas:/{print; exit}' "$OUT" | grep -q "replicas: 3" \
  || fail "prod Dapr control-plane must be HA (dapr-sentry replicas: 3)"

# 4. PodDisruptionBudgets render for the 4 request-serving services + OpenFGA (the authz chokepoint).
pdb=$(grep -c "kind: PodDisruptionBudget" "$OUT" || true)
[ "$pdb" -ge 5 ] || fail "prod must render app + OpenFGA PodDisruptionBudgets (>=5), got $pdb"
grep -q "name: lance-ns-openfga$" "$OUT" || fail "prod is missing the OpenFGA PDB"

# 5. Anti-affinity: the replicas:2 services spread across nodes (else one node loss defeats their PDB).
spread=$(grep -c "topologySpreadConstraints:" "$OUT" || true)
[ "$spread" -ge 4 ] || fail "prod must spread the 4 multi-replica services across nodes (>=4), got $spread"

# 6. Resource tiers: the memory-heavy workloads (catalog Arrow buffer, age dual-store, rustfs data plane)
# get a 1Gi limit above the shared 512Mi default. The default render tiers NOTHING to 1Gi (verified), so a
# non-zero count here proves the per-workload tiers apply on the prod overlay only.
tiers=$(grep -c "memory: 1Gi" "$OUT" || true)
[ "$tiers" -ge 3 ] || fail "prod must tier the memory-heavy workloads (catalog/age/rustfs) to 1Gi, got $tiers"

# 7. Alerting engine (P3b): vmalert + Alertmanager deployed, vmalert wired to GreptimeDB's PromQL endpoint,
# and the PROVEN rules actually mounted (a known alertname must appear — proves .Files.Get loaded rules.yml,
# not an empty ConfigMap). Off on the default render.
grep -q "name: lance-ns-vmalert$" "$OUT" || fail "prod must deploy vmalert (the alert evaluator)"
grep -q "name: lance-ns-alertmanager$" "$OUT" || fail "prod must deploy Alertmanager"
grep -q "datasource.url=http://lance-ns-greptimedb-standalone:.*prometheus" "$OUT" \
  || fail "vmalert must query GreptimeDB's PromQL endpoint"
grep -q "LineageOutboxNotDraining" "$OUT" || fail "the proven alert rules must be mounted into vmalert"

echo "✓ prod-render-check: NetworkPolicy=$np, OpenFGA=3, Dapr-HA on, PDBs=$pdb, spread=$spread, tiers=$tiers, alerting on"
