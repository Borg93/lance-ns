import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// The table-registry read the /admin/access picker offers as entry points (GET-only, session
// bearer-forwarded — the catalog's own gates decide what the caller may list).
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
