# Lance Lineage — web UI

A SvelteKit (Svelte 5 + Bun) dashboard for the medallion demo. It polls the lineage service every
2s and shows four live views of what's happening:

- **Status** — the live run board from `GET /runs`: each run's current state folded from its
  OpenLineage lifecycle (`START → RUNNING → COMPLETE/FAIL`), with a state pill, a **GSAP**-animated
  progress bar (the custom `progress{done,total}` facet), author/outputs, and the error on failures.
  Runs in flight pulse; the Svelte Flow nodes get a matching run-state **ring** (running = amber
  pulse, complete = green, failed = red). This is the *live* view — distinct from the durable
  provenance graph.
- **Graph** — the medallion DAG via [Svelte Flow](https://svelteflow.dev): nodes coloured by layer
  with their S3 `source_uri`, governance tags, Lance version chips (silver **v1 → v2**), and a red
  badge on the failed run. Edges animate in data-flow direction.
- **Events** — the Marquez-style feed from `GET /events`: each ingested OpenLineage event with its
  full facets JSON (schema / dataSource / tags / version / errorMessage), newest first.
- **Storage (S3)** — from `GET /demo/datasets`: each real Lance dataset on RustFS, its schema **at
  every Lance version** (so you watch `embedding` then `caption` appear on silver), row counts, and
  gold's embedded JSONB lineage.

UI chrome (tabs) uses [bits-ui](https://bits-ui.com); status-board animations use
[GSAP](https://gsap.com); the server proxies `/api/*` to the lineage service so the browser stays
same-origin (no CORS).

## Run

The UI needs the demo stack up (`scripts/medallion_demo.sh` brings up RustFS + lineage + this UI).

```bash
# Full stack (Docker) — UI at http://localhost:5173, ports overridable to dodge local clashes:
DEMO_S3_PORT=9100 DEMO_LINEAGE_PORT=8001 DEMO_WEB_PORT=5173 ./scripts/medallion_demo.sh
# then be the producer (trigger one OpenLineage event at a time, watch the UI):
S3_ENDPOINT=http://localhost:9100 LINEAGE_URL=http://localhost:8001 \
  uv run scripts/medallion_demo.py --step 1   # then --step 2, 3, 4, 5

# …or develop the UI on the host against an already-running lineage service:
cd web && bun install
LINEAGE_API=http://localhost:8001 bun run dev        # http://localhost:5173 (vite proxy)
```

## Stack

SvelteKit 2 · Svelte 5 (runes) · `@xyflow/svelte` (Svelte Flow) · `bits-ui` · `gsap` · `svelte-adapter-bun`.
`bun run build` → `bun ./build/index.js`. `LINEAGE_API` selects the upstream lineage service
(`http://lineage-api:8000` in compose, `http://localhost:8001` locally).
