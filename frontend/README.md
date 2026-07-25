# frontend — Turborepo workspace (bun + SvelteKit micro-frontend zones, the rask shape)

The frontend is decomposed into **seven independently-built SvelteKit zones** (the rask micro-frontend
shape), so the rask merge is a **directory graft**. Each zone is its own SvelteKit app + Bun SSR server
(`svelte-adapter-bun`), served under a base path and composed by Ingress zone-routing in the cluster
(the dev microfrontends proxy locally). Everything a zone does NOT own itself — the design system, the
auth/BFF seam, the lineage and media clients — lives in a workspace package.

```
frontend/
  package.json      # workspace root — bun workspaces, turbo pipeline;
                    #   //#lint and //#fmt:check ROOT tasks run eslint / prettier once repo-wide
  turbo.json        # build/check/test/test:e2e task graph (^build ordering, cached)
  eslint.config.js  # the single flat ESLint config (the sole linter)
  eslint-rules/     # the local cross-zone-reload rule (a cross-zone <a> MUST hard-navigate)
  components/frontends/
    home/           # catch-all zone (base '/'); owns the OIDC /auth/{login,callback,logout} routes
    data/           # /data — namespaces, tables, warehouses
    lineage/        # /lineage — the lineage graph explorer
    models/         # /models — model registry, experiments, pipeline
    admin/          # /admin — audit, DLQ, and the live control-plane activity feed (query.live)
    media/          # /media — semantic search, the embedding atlas, the derivation workflow
    annotator/      # /annotator — the Pixi labeling canvas
  packages/
    rask-ui/        # @rask/ui — shared shadcn-svelte design system on bits-ui 2 (AppShell + nav-config)
    api/            # @rask/api — the cross-cutting seam, by subpath:
                    #     .                  gateway rewrite · valibot parse · the frozen /v1/me contract
                    #     /client            the browser-side BFF client, bound per zone in $lib/http
                    #     /lineage           lineage domain types + the typed lineage-plane client
                    #     /generated/*       the OpenAPI output (bun run gen:types) — never hand-edited
                    #     /oidc /bff         server-only: PKCE + sealed session, and the zone wiring
                    #                        factories (hooks, layout load, catalog/lineage/viewer proxies)
    ui/             # @lance/ui — the pre-merge media design system; folding into @rask/ui
    media-api/      # @lance/media-api — the media-plane client (descriptor/DatasetView, Arrow envelopes)
    engine/         # @lance/engine — the Pixi canvas engine, tools and layer store
    labeling/       # @lance/labeling — annotation history, tag writer, job clients
    config/         # @lance/config — the shared tsconfig base
```

Note the two API packages are different layers, not duplicates: `@rask/api` is the **BFF/auth seam**
every zone's server wiring goes through, while `@lance/media-api` is the **typed client for the media
services** (viewer/search/annotator). It was previously named `@lance/api` in a `media-api/` directory,
which read as if it were the generic one.

Commands (root): `bun install` · `bun run build` · `bun run check` · `bun run lint` · `bun run fmt:check`
(CI-exact; `bun run fmt` rewrites) · `bun run test:e2e` · `bun run gen:types` (regenerates the OpenAPI
types from `../docs/*-openapi.json`). Each zone image builds from the parametrized
`.docker/frontend.dockerfile` (`--build-arg APP=<zone>` → `lance-<zone>:dev`); runtime contract
`bun ./build/index.js`, uid 1000. `make frontend-images` / `make frontend-load` build + side-load them all.

Adding a zone = `components/frontends/<name>` (its own `svelte.config.js` with `paths.base`) + the chart's
`frontend.apps` list + the Ingress route + an entry in `components/frontends/home/microfrontends.json`.
Its `hooks.server.ts`, `+layout.server.ts` and BFF catch-all routes are one line each — the factories in
`@rask/api/bff` (`makeZoneHooks`, `zoneLayoutLoad`, `makeCatalogProxy`, `makeLineageProxy`,
`makeViewerProxy`); its `src/lib/http.ts` binds `@rask/api/client` to the zone's base path. Remote
functions (`query`/`query.live`) are enabled per zone (`kit.experimental.remoteFunctions` +
`compilerOptions.experimental.async`); shared UI lives in `@rask/ui`.
