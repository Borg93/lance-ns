# frontend — Turborepo workspace (bun + SvelteKit micro-frontend zones, the rask shape)

The frontend is decomposed into **four independently-built SvelteKit zones** (the rask micro-frontend
shape), so the rask merge is a **directory graft**. Each zone is its own SvelteKit app + Bun SSR server
(`svelte-adapter-bun`), served under a base path and composed by Ingress zone-routing in the cluster
(the dev composition proxy locally). Everything a zone does NOT own itself — the design system, the
auth/BFF seam, the lineage and media clients — lives in a workspace package.

A zone boundary costs a full document load, so it has to buy something. These four each do: `home` is
the landing and owns the OIDC round-trip (and stays separate for the rask compute merge); `lakehouse`
is the governed estate; `annotator` is split from `media` to keep 17 MB of Pixi + OpenCV out of the
bundle of someone who came to search. Their backends are **not** the same set and the chart no longer
pretends they are — media reaches viewer, search and the annotator service (the workflow's tag write
and batch submit); the annotator reaches viewer and the annotator service, and never search. Each pod
gets exactly the upstreams its own BFF routes read, and `@repo/zone-contract` fails if that drifts.
The catalog, lineage,
models and admin areas used to be four more zones — one backend plane, one shared client, one nav
panel, and one shared image tag between them — so they paid four SSR servers and a hard reload per hop
and collected no independent-deploy payoff. They are areas of `lakehouse` now.

```
frontend/
  package.json      # workspace root — bun workspaces; scripts ONLY delegate to turbo
  turbo.json        # build/check/check:tsgo/test/test:e2e/lint/fmt task graph (^build ordering, cached)
  TOOLING.md        # which of oxlint/oxfmt/eslint/prettier owns what, and why it is not just two tools
  .oxlintrc.json    # oxlint — .ts/.js/.mjs
  .oxfmtrc.json     # oxfmt — .ts/.js/.mjs
  eslint.config.js  # ESLint — .svelte + *.svelte.ts only
  eslint-rules/     # the local cross-zone-reload rule (a cross-zone <a> MUST hard-navigate)
  components/frontends/
    home/           # catch-all zone (base '/'); owns the OIDC /auth/{login,callback,logout} routes
    lakehouse/      # /lakehouse — the governed estate, four AREAS in one router:
                    #     /lakehouse/data     projects, tables, namespaces, warehouses
                    #     /lakehouse/lineage  the lineage graph explorer
                    #     /lakehouse/models   model registry, experiments, pipeline
                    #     /lakehouse/admin    access, tenants, audit, events, streams, DLQ
                    #                         (estate-admin gated, fail-closed, in the root layout)
    media/          # /media — semantic search, the embedding atlas, the derivation workflow
    annotator/      # /annotator — the Pixi labeling canvas (split for bundle isolation, not domain)
  packages/           # ALL under one vendor-neutral scope: `rask` and `lance` are both temporary names
                    #   (rask becomes compute), and @repo/* is turborepo's own convention, so nothing
                    #   here has to be renamed again when they change.
    ui/             # @repo/ui — THE design system: shadcn-svelte on bits-ui 2, AppShell + nav-config.
                    #   The second UI package (@lance/ui) is folded in; every component it exported that
                    #   anything imported now lives here, and four components that existed but were
                    #   missing from the exports map are reachable at last (that gap is what kept the
                    #   second package alive).
    api/            # @repo/api — the cross-cutting seam, by subpath:
                    #     .                  gateway rewrite · valibot parse · the frozen /v1/me contract
                    #     /client            the browser-side BFF client, bound per zone in $lib/http
                    #     /lineage           lineage domain types + the typed lineage-plane client
                    #     /generated/*       the OpenAPI output (bun run gen:types) — never hand-edited
                    #     /oidc /bff         server-only: PKCE + sealed session, and the zone wiring
                    #                        factories (hooks, layout load, catalog/lineage/viewer proxies)
    media-api/      # @repo/media-api — the media-plane client (descriptor/DatasetView, Arrow envelopes)
    engine/         # @repo/engine — the Pixi canvas engine, tools and layer store
    labeling/       # @repo/labeling — annotation history, tag writer, job clients
    config/         # @repo/config — the shared tsconfig base
    zone-contract/  # @repo/zone-contract — everything about the zone SPLIT that no type or build can
                    #   check, and the things that kept silently drifting when nobody did:
                    #     · the manifest agrees — microfrontends.json, each svelte.config.js base, each
                    #       vite.config.ts port, chart/values.yaml, and the package name turbo routes by
                    #     · one config per tool, at the root — no per-package .oxlintrc/.oxfmtrc leftover
                    #     · nothing outside the frontend names a retired package or zone (the dockerfile,
                    #       chart, CI workflow, dagger module, verification scripts)
                    #     · every BFF route has a caller — a route with no caller is a hole to a backend
                    #     · budget.json — the per-zone gzipped client-bundle ceiling
                    #   plus the local composition proxy driven by the same routing config
                    #   (`bun run dev` → one origin on :5200, like the cluster Ingress)
```

Note the two API packages are different layers, not duplicates: `@repo/api` is the **BFF/auth seam**
every zone's server wiring goes through, while `@repo/media-api` is the **typed client for the media
services** (viewer/search/annotator). One is how a zone's server talks to the estate; the other is how
the browser talks to the media plane.

Commands (root): `bun install` · `bun run dev` (all four zones **plus the composition proxy**, so the
estate is one origin at <http://localhost:5200> exactly as it is behind the Ingress — `bun run dev:zones`
for the raw per-port servers) · `bun run build` · `bun run check` · `bun run lint` · `bun run fmt:check`
(CI-exact; `bun run fmt` rewrites) · `bun run test:e2e` · `bun run gen:types` (regenerates the OpenAPI
types from `../docs/*-openapi.json`). Lint and format are split across two toolchains —
**oxlint + oxfmt own `.ts`/`.js`, ESLint + Prettier own `.svelte`** — see [TOOLING.md](TOOLING.md).
Each zone image builds from the parametrized
`.docker/frontend.dockerfile` (`--build-arg APP=<zone>` → `lance-<zone>:dev`); runtime contract
`bun ./build/index.js`, uid 1000. `make frontend-images` / `make frontend-load` build + side-load them all.

Adding a zone = `components/frontends/<name>` (its own `svelte.config.js` with `paths.base`, and a
package **named for the directory** — turbo resolves routing keys against package names) + the chart's
`frontend.apps` list + the Ingress route + an entry in `components/frontends/home/microfrontends.json`
with a unique dev port. `@repo/zone-contract`'s tests fail if any of those four disagree.
Its `hooks.server.ts`, `+layout.server.ts` and BFF catch-all routes are one line each — the factories in
`@repo/api/bff` (`makeZoneHooks`, `zoneLayoutLoad`, `makeCatalogProxy`, `makeLineageProxy`,
`makeViewerProxy`); its `src/lib/http.ts` binds `@repo/api/client` to the zone's base path. Remote
functions (`query`/`query.live`) are enabled per zone (`kit.experimental.remoteFunctions` +
`compilerOptions.experimental.async`); shared UI lives in `@repo/ui`.
