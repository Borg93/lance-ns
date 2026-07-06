#!/usr/bin/env bash
# Seed the medallion mover service-identity grants into OpenFGA, so the FGA-enforced movers
# (chart value medallion.fgaEnabled=true) are authorized to produce their target stage:
#   - the writer movers (raw→bronze, bronze→silver) get `writer` on the warehouse (→ can_create_table)
#   - the silver→gold mover gets `validator` on the gold namespace (→ can_promote)
# Revoke the last grant (`fga tuple delete ... validator namespace:gold`) to SEE the enforcement: the
# silver→gold mover is then denied and the cascade stops at silver — a plain writer cannot promote.
#
# Prereq: the catalog has provisioned the model, and OpenFGA is reachable. Port-forward first:
#   kubectl port-forward svc/lance-ns-openfga 8081:8080 &
#   OPENFGA_API_URL=http://localhost:8081 scripts/seed_medallion_fga.sh
set -euo pipefail

BIN="$(cd "$(dirname "$0")/.." && pwd)/.localbin"
API="${OPENFGA_API_URL:-http://localhost:8081}"
WAREHOUSE="warehouse:lance_catalog"

SID="$("$BIN/fga" store list --api-url "$API" \
  | python3 -c "import sys,json;print([s['id'] for s in json.load(sys.stdin)['stores'] if s['name']=='lance-catalog'][0])")"
echo "store: $SID"

w() { "$BIN/fga" tuple write --api-url "$API" --store-id "$SID" "$@" >/dev/null 2>&1 || true; }

# medallion stage namespaces under the warehouse (so the rung cascade reaches them) — the MEDIA lane's
# namespaces included: without them the media mover's can_create_table check on namespace:silver-media
# finds no parent chain and the governed cascade silently DROPs every media trigger (audit blocker).
w "$WAREHOUSE" parent namespace:bronze
w "$WAREHOUSE" parent namespace:silver
w "$WAREHOUSE" parent namespace:gold
w "$WAREHOUSE" parent namespace:bronze-media
w "$WAREHOUSE" parent namespace:silver-media
# writer movers → can_create_table on their stage; the promoter mover → can_promote on gold
w user:service-raw-to-bronze writer "$WAREHOUSE"
w user:service-bronze-to-silver writer "$WAREHOUSE"
w user:service-media-to-silver writer "$WAREHOUSE"
w user:service-silver-to-gold validator namespace:gold

echo "✓ seeded medallion mover grants (writers incl. media lane + the silver→gold validator) into store $SID"
