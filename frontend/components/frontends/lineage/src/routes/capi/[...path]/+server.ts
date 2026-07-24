import { env } from '$env/dynamic/private';
import { json } from '@sveltejs/kit';
import { makeBackendProxy } from '@rask/api/bff';
import type { RequestHandler } from './$types';

// Same-origin proxy to the CATALOG service (the /api proxy covers lineage). The catalog is OIDC-only (no
// service-token door), so the only credential ever attached is the signed-in user's bearer — single-sourced
// in @rask/api/bff. Reads flow through the proxy; WRITES are allowlisted per path (below), never blanket —
// the confused-deputy stance from rask/apps/web.
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const GET = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });

// The dataset detail page's access panel (#72 grant/revoke) POSTs here. It used to meet the GET-only
// proxy and take a 405 on every attempt, so the panel read "unavailable" permanently — a whole feature
// dead in front of a working backend (found by the 2026-07-24 UX audit). The write door opens for THESE
// paths only: the per-object access mutations the panel actually issues. A new write surface must add its
// own pattern here deliberately, so nothing becomes writable by accident. The allowlist lives next to the
// proxy it guards rather than in a nested route on purpose: a `capi/v1/[kind]/…` branch would shadow this
// catch-all for every GET beneath it (the SvelteKit no-backtrack landmine, three prior instances).
const WRITABLE = /^\/v1\/(?:table|namespace)\/[^/]+\/access\/(?:grant|revoke)$/;

const writeProxy = makeBackendProxy({
	backendUrl: CATALOG_API,
	stripPrefix: /^\/capi/,
	// A write must be attributable to a real user: fail closed at the BFF, never forward anonymously.
	requireSession: true,
});

export const POST: RequestHandler = async (event) => {
	// Base-aware like the proxy itself: the built server sees `/lineage/capi/…`, dev sees `/capi/…`.
	const path = event.url.pathname.replace(/^(?:\/[^/]+)?\/capi/, '');
	if (!WRITABLE.test(path)) {
		return json({ detail: 'this path is read-only through the zone proxy' }, { status: 405 });
	}
	return writeProxy(event);
};
