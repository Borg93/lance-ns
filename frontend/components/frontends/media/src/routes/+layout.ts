// Client-rendered SPA on the Bun-server build target (svelte-adapter-bun):
// `ssr = false` keeps every route browser-rendered (WebGPU, localStorage, and
// the descriptor fetch never run server-side); the Bun server serves the shell
// + assets and the client renders. `prerender = false` — the app is dynamic
// (query-param driven, data from the backend), so there is nothing to bake at
// build time; the server serves routes directly.
export const ssr = false;
export const prerender = false;
