#!/usr/bin/env bash
# P5 live proof: a REAL per-user Dex login driven through the INGRESS (one origin, all zones), asserting
# the sealed session cookie carries ACROSS zones (sign in on /data → still signed in on /admin) + per-user
# authz through the zones' BFF (alice, a produce-admin → a governed surface 2xx; bob → 403). Drives the LIVE
# kind `lance` cluster with the P5 micro-frontend zones deployed OIDC-on behind ingress-nginx.
#
# Prereq (see docs/DEPLOY.md "the cross-zone drive"): the 5 zone images built + kind-loaded, ingress-nginx
# installed, and `helm upgrade … --set auth.enabled=true --set ingress.enabled=true
# --set frontend.oidc.enabled=true --set frontend.oidc.publicIssuer=http://lance-ns-dex:5556/dex
# --set frontend.oidc.publicOrigin=http://localhost:8090 --set frontend.oidc.sessionSecret=<48>` applied,
# then `kubectl rollout restart deploy/lance-ns-dex`. I mutate nothing on the cluster; run me OUTSIDE auto
# mode (or `!`-prefix) — the port-forwards are read-only. The browser↔Dex host-resolver fix lives in the .mjs.
#
#   bash scripts/verify_cross_zone_oidc.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$PWD/.localbin:$PATH"
RELEASE="${RELEASE:-lance-ns}"
ORIGIN_PORT="${ORIGIN_PORT:-8090}" # must equal frontend.oidc.publicOrigin's port (the registered redirect URI)
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
fail() { echo "!! FAIL: $*"; exit 1; }

# The single origin is the ingress-nginx controller (path-routes every zone); Dex is forwarded for the
# browser's host-resolver rule.
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller "$ORIGIN_PORT:80" >/tmp/pf-ingress.log 2>&1 & PIDS+=($!)
kubectl port-forward "svc/$RELEASE-dex" 5556:5556 >/tmp/pf-dex.log 2>&1 & PIDS+=($!)
for i in $(seq 1 30); do
  w=$(curl -s -o /dev/null -w '%{http_code}' -m2 "http://localhost:$ORIGIN_PORT/data" 2>/dev/null || true)
  d=$(curl -s -o /dev/null -w '%{http_code}' -m2 http://localhost:5556/dex/.well-known/openid-configuration 2>/dev/null || true)
  [ "$w" = "200" -o "$w" = "308" ] && [ "$d" = "200" ] && { echo "✓ forwards ready (ingress/data=$w dex=$d)"; break; }
  [ "$i" = "30" ] && { echo "ingress=$w dex=$d"; cat /tmp/pf-ingress.log /tmp/pf-dex.log; fail "port-forwards never became ready"; }
  sleep 1
done

# The @playwright/test browser lives in the lineage zone's node_modules (any zone has it); run from there.
cd frontend/components/frontends/lineage
ORIGIN="http://localhost:$ORIGIN_PORT" node "$ROOT/scripts/verify_cross_zone_oidc.mjs"
