// @rask/api — shared frontend data layer, split by domain. JIT TS: apps import the source directly
// (Vite/svelte-check transpile it) — no build. The `.` entry is CLIENT-SAFE (no node:crypto / $env):
//   • gateway  — the single-sourced SSR `/api/*` → in-cluster gateway rewrite (handleFetch factory).
//   • parse    — the valibot parse-don't-validate boundary for typed client responses.
//   • me       — the frozen `GET /v1/me` identity contract (schema/types) + the BFF-side fetchMe helper.
// Server-only auth lives behind subpaths so it never reaches a client bundle:
//   • @rask/api/oidc — the OIDC crypto seam (PKCE, sealed AES-256-GCM session cookie).
//   • @rask/api/bff  — the SvelteKit BFF factories (makeOidcConfig / makeSessionHandle / makeBackendProxy).
export * from './gateway';
export * from './parse';
export * from './me';
