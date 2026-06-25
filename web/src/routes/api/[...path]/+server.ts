import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

// Same-origin proxy to the lineage service so the browser never needs CORS. In compose this points
// at the in-cluster service (LINEAGE_API=http://lineage-api:8000); locally it defaults to :8001.
const LINEAGE_API = env.LINEAGE_API ?? 'http://localhost:8001';

export const GET: RequestHandler = async ({ url, fetch }) => {
	const target = LINEAGE_API + url.pathname.replace(/^\/api/, '') + url.search;
	try {
		const upstream = await fetch(target);
		return new Response(upstream.body, {
			status: upstream.status,
			headers: {
				'content-type': upstream.headers.get('content-type') ?? 'application/json'
			}
		});
	} catch (err) {
		return new Response(JSON.stringify({ error: String(err) }), {
			status: 502,
			headers: { 'content-type': 'application/json' }
		});
	}
};
