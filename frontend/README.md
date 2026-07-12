# frontend — Turborepo workspace (bun + SvelteKit, the rask microfrontend shape)

Restructured 2026-07-11 (Batch 12) so the rask merge is a **directory graft**: rask runs SvelteKit
microfrontends consuming a shared component library; this workspace mirrors that shape.

```
frontend/
  package.json      # workspace root — bun workspaces, turbo 2.10 pipeline
  turbo.json        # build/check/test/test:e2e task graph (^build ordering, cached)
  apps/
    web/            # lance-lineage-web — the lineage explorer (SvelteKit, Svelte 5 runes)
  packages/
    ui/             # @lance/ui — shared Svelte 5 components + GSAP {@attach} factories
                    #   (transport- AND framework-agnostic BY RULE: no fetch/API clients,
                    #   no $lib/$app imports; a bun test sweeps every source to enforce it)
    config/         # @lance/config — shared tsconfig preset (extended by apps/* and packages/*)
```

Commands (root): `bun install` · `bunx turbo run build` · `bunx turbo run check test` ·
`bunx turbo run test:e2e --filter=lance-lineage-web`. The web image
(`.docker/web.dockerfile`) builds via the same turbo graph; runtime contract unchanged
(`bun ./build/index.js`, port 3000, uid 1000).

Adding a microfrontend later = `apps/<name>` + a `dependsOn: ^build` ride on the existing
pipeline; adding shared components = `packages/ui/src` + the export test.
