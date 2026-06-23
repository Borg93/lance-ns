#!/usr/bin/env bash
# Demo: grant a SECOND user (bob) `reader` on a namespace and watch the OpenFGA
# (Zanzibar) cascade give him read access to every table in it — while writes stay
# denied. alice creates the resources (app auto-seeds her ownership); the only
# hand-written tuple is bob's namespace-level reader grant, to show inheritance.
#
#   ./scripts/seed_demo.sh        # against the running auth stack
set -euo pipefail

SERVER=${SERVER:-http://localhost:2333}
DEX=${DEX:-http://localhost:5556/dex}
FGA=${FGA:-http://localhost:8080}

tok()  { curl -s -X POST "$DEX/token" -d grant_type=password -d client_id=lance-catalog \
           -d "username=$1" -d password=password -d scope=openid \
           | python3 -c 'import sys,json;print(json.load(sys.stdin)["id_token"])'; }
sub()  { printf '%s' "$1" | python3 -c \
           'import sys,base64,json;p=sys.stdin.read().split(".")[1];p+="="*(-len(p)%4);print(json.loads(base64.urlsafe_b64decode(p))["sub"])'; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

ALICE=$(tok alice@example.com); BOB=$(tok bob@example.com); BSUB=$(sub "$BOB")
A=(-H "Authorization: Bearer $ALICE"); B=(-H "Authorization: Bearer $BOB")
J=(-H 'content-type: application/json'); ARR=(-H 'content-type: application/vnd.apache.arrow.stream')
STORE=$(curl -s "$FGA/stores" | python3 -c 'import sys,json;print(json.load(sys.stdin)["stores"][0]["id"])')

NS="shared$$"; TID="$NS\$readings"
ARROW=$(mktemp --suffix=.arrows)
uv run --no-sync python - "$ARROW" <<'PY'
import sys, pyarrow as pa
t = pa.table({"id": pa.array([1, 2, 3], pa.int64())})
with pa.OSFile(sys.argv[1], "wb") as s:
    with pa.ipc.new_stream(s, t.schema) as w:
        w.write_table(t)
PY

echo "== alice creates namespace + table ($NS) — app auto-seeds alice owner =="
code -X POST "$SERVER/v1/namespace/$NS/create" "${A[@]}" "${J[@]}" -d '{}' >/dev/null
code -X POST "$SERVER/v1/table/$TID/create"   "${A[@]}" "${ARR[@]}" --data-binary @"$ARROW" >/dev/null

echo "== BEFORE grant =="
echo "  bob read table   -> $(code -X POST "$SERVER/v1/table/$TID/describe" "${B[@]}")   (403: bob has no grant)"

echo "== grant bob reader on the NAMESPACE (the only hand-written tuple) =="
curl -s -X POST "$FGA/stores/$STORE/write" "${J[@]}" \
  -d "{\"writes\":{\"tuple_keys\":[{\"user\":\"user:$BSUB\",\"relation\":\"reader\",\"object\":\"namespace:$NS\"}]}}" \
  -o /dev/null -w "  wrote  user:$BSUB reader namespace:$NS -> %{http_code}\n"

echo "== AFTER grant — the cascade (namespace reader => table reader) =="
echo "  bob read table     -> $(code -X POST "$SERVER/v1/table/$TID/describe"  "${B[@]}")   (200: cascaded!)"
echo "  bob count_rows     -> $(curl -s -X POST "$SERVER/v1/table/$TID/count_rows" "${B[@]}")        (reads the data)"
echo "  bob write (insert) -> $(code -X POST "$SERVER/v1/table/$TID/insert" "${B[@]}" "${ARR[@]}" --data-binary @"$ARROW")   (403: reader != writer)"
echo "  bob drop           -> $(code -X POST "$SERVER/v1/table/$TID/drop"   "${B[@]}")   (403: reader != owner)"
rm -f "$ARROW"
echo "== done: bob can READ alice's namespace tables, cannot WRITE/DROP =="
