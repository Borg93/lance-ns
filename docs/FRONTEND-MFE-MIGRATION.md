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
- [x] **P1 DONE** — adopted rask's full `@rask/ui` shadcn-svelte design system verbatim into
  `packages/rask-ui` (18 bits-ui components + the shell AppShell/app-sidebar/nav-main/nav-user/
  project-switcher/breadcrumb + hooks + utils; storybook/stories excluded). `nav-config.ts` swapped to the
  4 lance domains (Data/Lineage/Models/Admin, each with collapsible leaves + active-match); `nav-user`
  already threads a `NavUser` prop (the OIDC session value flows in P3). VERIFIED: `@rask/ui` svelte-check
  0/0; build (svelte-package→dist) ✓; `@rask/ui` tests 13 pass incl. nav-config (4 domains + active-match);
  all 5 zones SSR-build with the full AppShell (render smoke); apps/web green (bits-ui@1.8 nested vs @rask/ui
  bits-ui@2.18); both linter pairs green.
- [x] **P2 DONE** — folded the OIDC BFF into `@rask/api` (the cross-cutting auth seam, single-sourced like
  the backend services). Moved apps/web's env-free `oidc-core` (PKCE + AES-256-GCM sealed cookie) →
  `@rask/api/oidc` (server-only subpath; the client-safe `.` entry stays crypto-free) + its unit test →
  in-package (retargeted bun:test→vitest). New `@rask/api/bff` = `makeOidcConfig(env)` + `makeSessionHandle`
  (per-request session hydration + stale-drop) + `makeBackendProxy` (bearer-forward with the READ-only
  service-cred fallback / confused-deputy guard) — env-free (config passed in). `@rask/api/parse` = the
  valibot parse-don't-validate boundary. apps/web's `oidc-core.ts` is now a re-export shim of `@rask/api/oidc`
  (its many importers stay green; one source of truth). Each zone's `hooks.server.ts` is 3 lines:
  `makeSessionHandle(makeOidcConfig(env))` + `makeGatewayHandleFetch(...)`; `app.d.ts` = `interface Locals
  extends AuthLocals`. VERIFIED: `@rask/api` tsgo clean; 22 in-package tests pass; zones check 10/10; apps/web
  build+check+test(51) green via the shim; lint/fmt both pairs green. (Full typed catalog/lineage/medallion
  clients grow in P3 as each zone moves its routes; the parse+proxy+client seam is in place.)
- [x] **P3 route migration DONE** — all four domain zones built by MOVING routes from apps/web, each a
  verified green push:
  - data (`5cf53a6`,`a73b899`,`ef8d646`) — namespaces·warehouses·tables (incl. the 1,569-line TableDetail);
  - models (`19fcccb`) — registry·experiments·pipeline + the medallion trigger;
  - lineage (`7d847bd`) — the 1,521-line LineageExplorer graph + provenance;
  - admin (`888d38b`) — audit·dlq.
  `@rask/ui` grew every `@lance/ui` primitive it needed (Select, Chip, motion, SearchBar, StatusBoard) so
  the zones are 100% `@lance/ui`-free. apps/web is now a bare shell (auth + a migrated-root placeholder),
  still green. All 5 zones + shared packages + apps/web build+check(0/0)+test + lint/fmt green.
- [x] **P3 tail DONE** — per-zone Playwright harness + moved e2e specs, **61 tests green via
  `turbo run test:e2e`** (data 31 · models 12 · lineage 10 · admin 8). Each zone got a hermetic
  `playwright.config.ts` (dedicated e2e port + base-path routes + `page.route` mocks) + a `test:e2e`
  script; the specs moved out of apps/web (its routes moved in P3, so the suite was orphaned) into the
  owning zone, with goto paths base-prefixed and the old per-page `.navbar a.active` nav assertions
  rewritten to drive the shared AppShell sidebar (`data-active` + the cross-zone `data-sveltekit-reload`
  contract). apps/web keeps its separate *live* harness (`e2e-live/`). Two real gaps the specs caught,
  both fixed: (1) `@rask/ui` Select was a native `<select>` (broke every option-picking spec — a native
  option set can't be portal-driven) → reimplemented on **bits-ui@2** (portalled listbox) keeping the
  exact `@lance/ui` API so no call site changed; (2) nav-config root leaves (Registry=/models,
  Graph=/lineage) over-matched every sibling sub-route → **exact** matcher + **trailing-slash
  normalization** (a base-path zone root is `page.url.pathname === '/models/'`), +3 unit tests; and the
  ModelRegistry moved to the models zone root (was orphaned at `/models/models`). Commit `c912fac`.
- [x] **P4 composition — offline-proven.** The zones are composition-ready: every zone's `paths.base` +
  strictPort matches `home/microfrontends.json` routing (deterministic consistency proof passed), and
  each zone serves its base-path routes under `turbo run dev`. The **live** single-origin drive
  (cross-zone nav + Dex login persisting across zones + alice-allowed/bob-denied) runs behind the prod
  gateway and is folded into P5's cluster deploy (the local turbo dev-proxy hit an external port clash;
  auto-mode blocks the cluster mutation, so the live drive needs a user-approved `helm upgrade`).
- [ ] P5 — retire apps/web; chart (per-zone/multi-zone images + gateway path-routing + prod
  microfrontends config); DEPLOY docs; the live cross-zone OIDC drive on kind; global gate.
