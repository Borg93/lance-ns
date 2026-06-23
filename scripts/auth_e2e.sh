#!/usr/bin/env bash
# End-to-end auth check: Dex (OIDC) + OpenFGA (authz, Postgres) against the live stack.
# Brings the stack up with auth ON, gets a real token from Dex, and asserts the
# 401 (no token) / 403 (no grant) / allowed (after granting a tuple) chain.
#
#   ./scripts/auth_e2e.sh
set -euo pipefail

BASE=.docker/docker-compose.yml
AUTH=.docker/docker-compose.auth.yml
SERVER=http://localhost:2333
DEX=http://localhost:5556/dex
FGA=http://localhost:8080

echo "== bring up auth stack =="
docker compose -f "$BASE" -f "$AUTH" up -d
until curl -fsS "$FGA/healthz" >/dev/null 2>&1; do sleep 1; done
until curl -fsS "$DEX/.well-known/openid-configuration" >/dev/null 2>&1; do sleep 1; done
# Recreate the server once its deps are ready so OpenFGA provisioning succeeds.
docker compose -f "$BASE" -f "$AUTH" up -d --force-recreate --no-deps server
until curl -fsS "$SERVER/livez" >/dev/null 2>&1; do sleep 1; done
sleep 2

echo "== get id_token from Dex (alice@example.com / password) =="
TOKEN=$(curl -s -X POST "$DEX/token" \
  -d grant_type=password -d client_id=lance-catalog \
  -d username=alice@example.com -d password=password -d scope=openid \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id_token'])")
SUB=$(printf '%s' "$TOKEN" | python3 -c "import sys,base64,json;p=sys.stdin.read().split('.')[1];p+='='*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p))['sub'])")

STORE=$(curl -s "$FGA/stores" | python3 -c "import sys,json;print(sorted(json.load(sys.stdin)['stores'],key=lambda x:x['created_at'])[-1]['id'])")
MODEL=$(curl -s "$FGA/stores/$STORE/authorization-models" | python3 -c "import sys,json;print(json.load(sys.stdin)['authorization_models'][0]['id'])")

grant() {  # grant: <relation> <object>
  curl -s -X POST "$FGA/stores/$STORE/write" -H 'content-type: application/json' \
    -d "{\"writes\":{\"tuple_keys\":[{\"user\":\"user:$SUB\",\"relation\":\"$1\",\"object\":\"$2\"}]},\"authorization_model_id\":\"$MODEL\"}" >/dev/null
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

echo "== assertions =="
echo "no token            -> $(code -X POST "$SERVER/v1/namespace/db1/create" -H 'content-type: application/json' -d '{}')   (expect 401)"
echo "token, no grant     -> $(code -X POST "$SERVER/v1/namespace/db2/create" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{}')   (expect 403)"
grant writer "namespace:db1"
echo "token + writer      -> $(code -X POST "$SERVER/v1/namespace/db1/create" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{}')   (expect 200/409)"
grant reader "namespace:db1"
echo "token + reader      -> $(code -X POST "$SERVER/v1/namespace/db1/describe" -H "Authorization: Bearer $TOKEN")   (expect 200)"
