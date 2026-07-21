#!/usr/bin/env bash
# Phase 3 live proof: a REAL per-user Dex login driven in a headless browser + per-user authz through the
# BFF (alice, a produce-admin, opens the /produce door → 202; bob, no grant → 403). Drives the LIVE kind
# `lance` cluster. One self-contained process so the port-forwards stay alive for the browser drive.
#
# Prereq: web.oidc enabled on the release with publicOrigin=http://localhost:5280 (a helm upgrade --set
# web.oidc.enabled=true --set web.oidc.publicIssuer=http://lance-ns-dex:5556/dex
# --set web.oidc.publicOrigin=http://localhost:5280 --set web.oidc.sessionSecret=<48chars>, then roll web +
# restart dex). I mutate nothing on the cluster; run me OUTSIDE auto mode (or `!`-prefix) — the port-forwards
# are read-only. The reachability fix (chromium --host-resolver-rules) lives in verify_oidc_login.mjs.
#
#   bash scripts/verify_oidc_login.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$PWD/.localbin:$PATH"
RELEASE="${RELEASE:-lance-ns}"
WEB_PORT="${WEB_PORT:-5280}" # must equal web.oidc.publicOrigin's port (the registered redirect URI)
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
fail() { echo "!! FAIL: $*"; exit 1; }

pkill -f "port-forward.*$RELEASE-(web|dex)" 2>/dev/null || true
sleep 1
kubectl port-forward "svc/$RELEASE-web" "$WEB_PORT:3000" >/tmp/pf-web.log 2>&1 & PIDS+=($!)
kubectl port-forward "svc/$RELEASE-dex" 5556:5556 >/tmp/pf-dex.log 2>&1 & PIDS+=($!)
for i in $(seq 1 30); do
  w=$(curl -s -o /dev/null -w '%{http_code}' -m2 "http://localhost:$WEB_PORT/" 2>/dev/null || true)
  d=$(curl -s -o /dev/null -w '%{http_code}' -m2 http://localhost:5556/dex/.well-known/openid-configuration 2>/dev/null || true)
  [ "$w" = "200" ] && [ "$d" = "200" ] && { echo "✓ forwards ready (web=$w dex=$d)"; break; }
  [ "$i" = "30" ] && { echo "web=$w dex=$d"; cat /tmp/pf-web.log /tmp/pf-dex.log; fail "port-forwards never became ready"; }
  sleep 1
done

cd frontend/apps/web
WEB_URL="http://localhost:$WEB_PORT" node "$ROOT/scripts/verify_oidc_login.mjs"
