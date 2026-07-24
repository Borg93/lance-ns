import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';
import type { RequestHandler } from './$types';

// The /admin/access surface's narrow catalog pass-through: POST-only, allowlisted to the access
// sub-API on the two kinded objects (list / check / grant / revoke / graph — all owner-gated BY THE
// CATALOG; this route only bearer-forwards the signed-in user's session, never a service token).
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

const KINDS = new Set(['table', 'namespace']);
const ACTIONS = new Set(['list', 'check', 'grant', 'revoke', 'graph']);

const proxy = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });

export const POST: RequestHandler = (event) => {
	if (!KINDS.has(event.params.kind) || !ACTIONS.has(event.params.action)) {
		return new Response(JSON.stringify({ detail: 'not found' }), {
			status: 404,
			headers: { 'content-type': 'application/json' },
		});
	}
	return proxy(event);
};
