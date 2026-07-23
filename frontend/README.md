# frontend — Turborepo workspace (bun + SvelteKit micro-frontend zones, the rask shape)

The frontend is decomposed into **five independently-built SvelteKit zones** (the rask micro-frontend
shape), so the rask merge is a **directory graft**. Each zone is its own SvelteKit app + Bun SSR server
(`svelte-adapter-bun`), served under a base path and composed by Ingress zone-routing in the cluster
(the dev microfrontends proxy locally). They share two workspace packages.

```
frontend/
  package.json      # workspace root — bun workspaces, turbo 2.10 pipeline;
                    #   //#lint and //#fmt:check ROOT tasks run eslint / prettier once repo-wide
  turbo.json        # build/check/test/test:e2e task graph (^build ordering, cached)
  eslint.config.js  # the single flat ESLint config (the sole linter)
  components/frontends/
    home/           # catch-all zone (base '/'); owns the OIDC /auth/{login,callback,logout} routes
    data/           # /data — namespaces, tables, warehouses
    lineage/        # /lineage — the lineage graph explorer
    models/         # /models — model registry, experiments, pipeline
    admin/          # /admin — audit, DLQ, and the live control-plane activity feed (query.live)
  packages/
    rask-ui/        # @rask/ui — shared shadcn-svelte design system on bits-ui 2 (AppShell + nav-config)
    api/            # @rask/api — cross-cutting seam: OIDC/sealed-session, the BFF gateway, valibot parse
```

Commands (root): `bun install` · `bun run build` · `bun run check` · `bun run lint` · `bun run fmt:check`
(CI-exact; `bun run fmt` rewrites) · `bun run test:e2e`. Each zone image builds from the parametrized
`.docker/frontend.dockerfile` (`--build-arg APP=<zone>` → `lance-<zone>:dev`); runtime contract
`bun ./build/index.js`, uid 1000. `make frontend-images` / `make frontend-load` build + side-load all five.

Adding a zone = `components/frontends/<name>` (its own `svelte.config.js` with `paths.base`) + the chart's
`frontend.apps` list + the Ingress route. Remote functions (`query`/`query.live`) are enabled per zone
(`kit.experimental.remoteFunctions` + `compilerOptions.experimental.async`); shared UI lives in `@rask/ui`.
