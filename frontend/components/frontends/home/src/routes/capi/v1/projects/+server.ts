import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

// The estate-admin gallery pass-through: same-origin /capi/v1/projects → catalog GET /v1/projects,
// forwarding the signed-in user's bearer (the backend's estate-observer gate decides — no service
// fallback here, the tenant enumeration is a whole-estate disclosure).
export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
