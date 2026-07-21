import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// Same-origin proxy to the CATALOG service (the /api proxy covers lineage). The catalog is OIDC-only (no
// service-token door), so the only credential ever attached is the signed-in user's bearer — single-sourced
// in @rask/api/bff. GET-only: same confused-deputy stance as rask/apps/web (no blanket write proxy).
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
