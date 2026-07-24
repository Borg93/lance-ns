import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// The bare table LIST (`GET /capi/v1/table` → catalog `GET /v1/table`). This static branch
// (`capi/v1/table/[id]/…`) shadows the `capi/[...path]` catch-all for its whole subtree, and
// SvelteKit does NOT backtrack to the rest route when `[id]` is unfilled — so without this file
// the list 404s while every `[id]` action works (found live 2026-07-24: the tables panel rendered
// "Catalog unreachable (HTTP 404)"). Same GET-only user-bearer proxy as the catch-all.
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
