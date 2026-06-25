#!/usr/bin/env bash
# Reset the live demo to a CLEAN SLATE so you can drive it yourself from empty:
#   - wipes the Lance tables on S3 (RustFS)
#   - empties the lineage graph (Apache AGE)
#   - clears the in-memory events buffer (restarts lineage-api)
#
# Use the same DEMO_S3_PORT / DEMO_LINEAGE_PORT you launched the stack with, e.g.:
#   DEMO_S3_PORT=9100 DEMO_LINEAGE_PORT=8001 ./scripts/medallion_reset.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export DEMO_S3_PORT="${DEMO_S3_PORT:-9000}"
export DEMO_LINEAGE_PORT="${DEMO_LINEAGE_PORT:-8000}"

echo "== 1) wipe the Lance tables on S3 =="
S3_ENDPOINT="http://localhost:${DEMO_S3_PORT}" S3_ACCESS_KEY=rustfsadmin S3_SECRET_KEY=rustfsadmin S3_BUCKET=lakehouse \
  uv run --no-sync python scripts/medallion_demo.py --reset

echo "== 2) empty the lineage graph (Apache AGE) =="
docker exec lance-lineage-postgres psql -U lineage -d lineage -tA \
  -c "LOAD 'age'; SET search_path = ag_catalog, \"\$user\", public; SELECT drop_graph('lineage', true); SELECT create_graph('lineage');" >/dev/null

echo "== 3) clear the in-memory events buffer (restart lineage-api) =="
docker restart lance-lineage-api >/dev/null
until curl -fsS "http://localhost:${DEMO_LINEAGE_PORT}/livez" >/dev/null 2>&1; do sleep 2; done

echo
echo "== clean slate. You are the producer — trigger one OpenLineage event at a time: =="
echo "   S3_ENDPOINT=http://localhost:${DEMO_S3_PORT} LINEAGE_URL=http://localhost:${DEMO_LINEAGE_PORT} \\"
echo "     uv run python scripts/medallion_demo.py --step 1   # then --step 2, 3, 4, 5 (watch the UI)"
