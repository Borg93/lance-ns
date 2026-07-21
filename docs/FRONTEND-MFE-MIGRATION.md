# Frontend micro-frontend migration — mirror rask's zones architecture

**Goal:** restructure `frontend/` from ONE SvelteKit app (`apps/web`) into rask-style **routing-based
micro-frontend zones**, so catalog+lineage's UI drops into rask (`components/frontends/*`) as a clean
copy-over. Decisions (2026-07-21): cohesive-domain zones; restructure **in lance-ns** to mirror rask.

Grounded in the rask checkout at `rask/` (HEAD `6baa318`, pulled). Uses the `micro-frontends` (routing-based
zones) + `turborepo` skills.

## Target architecture (faithful to rask)

- Each zone = a **standalone SvelteKit app** under `frontend/components/frontends/<zone>/`:
  `svelte-adapter-bun`, `svelte.config.js` with `paths.base: '/<zone>'`, `vite.config.ts` with a strictPort
  from `microfrontends.json` + a `/api/*` → gateway proxy, its own `hooks.server.ts` / `app.html` / `app.css`
  / `routes` / `static`.
- Composition = **routing-based zones**: all zones run behind a `:3024`-style composition proxy (single
  origin → cross-zone nav). Cross-zone `<a>` links **hard-navigate** (`data-sveltekit-reload`), guarded by a
  local `eslint-rules/cross-zone-reload.js`.
- Shared **`@lance/ui/shell`** = the design-system `AppShell` (app-sidebar, nav-main, breadcrumb, nav-user,
  project-switcher) + `nav-config.ts` (the 4-domain IA). Every zone's `+layout.svelte` renders an identical
  `<AppShell pathname={page.url.pathname}>{@render children()}</AppShell>` → zero drift.
- Shared **`@lance/api`** = the **cross-cutting seam** (auth/authz/session/gateway — "similar in every MFE,
  like the backend"): the OIDC BFF (oidc-core sealed cookie, login/callback/logout helpers), the session
  decode + FGA-bearer-forwarding `handle`, and a single-sourced `makeCatalog/LineageHandleFetch` (SSR fetch
  rewrite to the in-cluster service). Each zone's `hooks.server.ts` becomes ~a few lines importing these.

## Zone decomposition (cohesion, low coupling)

| Zone | Routes (from `apps/web`) | Backend seam |
|---|---|---|
| **`models`** (MLflow-replacement dashboards) | `models`, `experiments`, `pipeline`, `medallion` | catalog `/v1/model/*`, medallion `/produce`+`/train`, lineage runs/metrics |
| **`lineage`** | `lineage` (graph/upstream/downstream/columns/runs/events) | lineage service (`/api`) |
| **`data`** (data-plane) | `tables`, `namespaces`, `warehouses` | catalog data-plane (`/capi`) |
| **`admin`** | `audit`, `dlq`, access/grants, maintenance policies, warehouse provisioning | catalog access/policies/maintenance, lineage `/admin/dlq` |

Cross-cutting (`auth`, the `capi`/`api`/`medallion` BFF proxies, session, Dapr/secret wiring) is NOT a zone —
it is shared in `@lance/api` and mounted per-zone via `hooks.server.ts` + a shared proxy route helper.

## Conventions to match (from rask)

- bun workspaces + turbo 2.9; **package tasks** (build/check/dev/test in each pkg; root only `turbo run`).
- svelte 5.56, `@sveltejs/kit` 2, vite 8, `svelte-adapter-bun`, tailwind 4 (`@tailwindcss/vite`),
  `@lucide/svelte`, `mode-watcher` (dark), `svelte-sonner` (Toaster).
- TypeScript 7 native preview (`@typescript/native-preview` + a `check:tsgo` task) — resolves the old
  `feedback-use-typescript-7` block (rask runs svelte-check on TS7 fine).
- prettier (tabs, singleQuote, printWidth 100, tailwind plugin); eslint 10 flat + `typescript-eslint` +
  `eslint-plugin-svelte` + local `eslint-rules/` (cross-zone-reload), tested via `vitest run eslint-rules`.

## Phased sequence

- **P0 — workspace scaffold.** Feature branch. Root `frontend/package.json` workspaces →
  `components/frontends/{data,lineage,models,admin}` + `packages/{ui,api,config}`. `turbo.json`,
  `microfrontends.json`, the `:3024` composition proxy, `eslint-rules/`, per-zone `dev:<zone>` scripts.
  `apps/web` stays until the last zone lands (no big-bang break).
- **P1 — shared `@lance/ui/shell`.** AppShell + app-sidebar + nav-main + `nav-config.ts` (Data/Lineage/
  Models/Admin domains) + breadcrumb + nav-user (wired to the real OIDC session) + tokens.css. Reuse the
  existing `@lance/ui` bits-ui components (Select/Button/Dialog).
- **P2 — shared `@lance/api`.** Extract oidc-core + session `handle` + FGA bearer-forwarding + the
  `capi`/`api`/`medallion` proxy helper + typed clients from `apps/web/src/lib/server` into the package.
- **P3–P6 — build each zone** (`data` first as the proof, then `lineage`, `models`, `admin`): scaffold the
  app, move its routes, thin `hooks.server.ts` (imports `@lance/api`), `paths.base`, vite proxy, `+layout`
  renders `<AppShell>`. Migrate the zone's e2e specs. Verify `turbo run build/check/lint/test` per zone.
- **P7 — cross-zone nav + composition.** `data-sveltekit-reload` on cross-zone links + the eslint rule;
  drive all zones behind the `:3024` proxy; live OIDC login still works across zones (session cookie shared
  on one origin).
- **P8 — retire `apps/web`**, update chart (`web.dockerfile` → per-zone images or one multi-zone image +
  the composition proxy), update DEPLOY docs, run the global gate.

## Scope finding — shared packages are a design-system ADOPTION, not just a route split

`@lance/ui` today is a small flat set (Chip, Select, SearchBar, StatusBoard on bits-ui). `@rask/ui` is a full
shadcn-svelte **design system** (`./button ./badge ./dialog ./dropdown-menu ./avatar ./collapsible ./card
./table ./checkbox ./alert-dialog ./progress ./sort-header ./sidebar ./shell ./utils ./styles/tokens.css`,
laid out as `src/lib/{components,hooks,shell,styles,utils}`). The AppShell renders on that system, so "exactly
similar / clean merge" means lance-ns adopts rask's `packages/ui` + `packages/api` as the shared foundation
(same layout; keep the `@rask/*` import names so the merge into rask is a no-op for the shared packages, and
the 4 new zones drop straight into `rask/components/frontends/`). Composition is **Turborepo-native
microfrontends** (`microfrontends.json` on the `home` default app + `turbo dev` proxy), not a hand-rolled proxy.

**Revised P1/P2:** vendor rask `packages/ui` (design system + shell) + `packages/api` (gateway/auth seam) into
`frontend/`, then extend the shell's `nav-config.ts` with the 4 lance domains and fold lance's OIDC BFF into
`@rask/api` (rask has "no auth yet" — lance contributes it). Migrate `apps/web`'s current `@lance/ui`
consumers onto the adopted system as each zone is built.

## Status

- [x] rask studied (zones, AppShell, `@rask/api` seam, microfrontends.json, cross-zone-reload, TS7/tsgo).
- [x] Decomposition locked (data/lineage/models/admin zones); plan doc; branch `feat/frontend-mfe`.
- [x] **P0 foundation DONE** — `frontend/` restructured to rask layout ALONGSIDE apps/web (coexistence
  proven). bun workspaces += `components/frontends/*`; MERGED turbo.json (+`check:tsgo`/`dev`, kept
  `test:e2e`/`//#lint`/`//#fmt:check`); `@rask/api` (tsgo seam) + `@rask/ui` at `packages/rask-ui` (minimal
  AppShell/Button + rask tokens.css) + 5 zone apps (`home` default + `data`/`lineage`/`models`/`admin`
  stubs, svelte-adapter-bun@1.0.1 patched, `paths.base`, tailwind-4 per-zone, strictPorts) +
  `microfrontends.json` + `eslint.config.js` + `eslint-rules/cross-zone-reload`. Toolchains scoped apart
  (oxlint/oxfmt = lance side; eslint/prettier = MFE dirs). VERIFIED: bun install clean (patch applied); TS6
  root / TS5 nested for apps/web; `turbo run build` 7✓, `check` 10✓ (svelte-check 0/0), `check:tsgo` @rask/api
  ✓; apps/web+@lance/ui green contract unchanged; microfrontends.json ports match; lint/fmt both pairs green;
  tests green (incl the cross-zone-reload unit test).
- [ ] P1 adopt full rask `@rask/ui` design system + nav-config (4 domains) + nav-user(OIDC).
- [ ] P2 fold OIDC BFF + catalog/lineage/medallion clients into `@rask/api`.
- [ ] P3..P8 (build zones from apps/web routes, cross-zone nav, retire apps/web, chart+docs, global gate).
