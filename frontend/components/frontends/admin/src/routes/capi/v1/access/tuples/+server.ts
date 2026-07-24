import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// The FGA workbench's tuple surface: same-origin pass-through to the catalog's estate-admin-gated
// /v1/access/tuples (gated BY THE CATALOG like /v1/events — this route only bearer-forwards the
// signed-in user's session, never a service token). GET lists/filters; POST writes a tuple; DELETE
// revokes one. The writes fail closed on a governed stack without a session (the write-route stance:
// a grant/revoke must be attributable to a real user).
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
export const POST = makeBackendProxy({
	backendUrl: CATALOG_API,
	stripPrefix: /^\/capi/,
	requireSession: true,
});
export const DELETE = makeBackendProxy({
	backendUrl: CATALOG_API,
	stripPrefix: /^\/capi/,
	requireSession: true,
});
