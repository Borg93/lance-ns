// @rask/api — shared frontend data layer (API client + types), split by domain.
// JIT TS: apps import the source directly (Vite/svelte-check transpile it) — no build.
// Server-only bits (remote functions, $env) stay per-app.
//
// P0: the single-sourced gateway rewrite seam. P2 folds in lance's OIDC BFF
// (oidc-core sealed cookie + session handle + FGA bearer-forwarding) + the typed
// catalog/lineage/medallion clients (parse-don't-validate with valibot).
export * from './gateway';
