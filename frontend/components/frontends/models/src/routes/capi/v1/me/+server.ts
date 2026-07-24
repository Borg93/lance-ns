import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// The frozen /v1/me identity pass-through: same-origin /capi/v1/me → catalog GET /v1/me, forwarding
// ONLY the signed-in user's bearer (no service fallback — identity is per-user by definition; anon
// stays the catalog's honest 401 and the navbar renders signed-out chrome).
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
