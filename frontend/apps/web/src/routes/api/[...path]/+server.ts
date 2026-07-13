import { env } from "$env/dynamic/private";
import type { RequestHandler } from "./$types";

// Same-origin proxy to the lineage service so the browser never needs CORS. In compose this points
// at the in-cluster service (LINEAGE_API=http://lineage-api:8000); locally it defaults to :8001.
const LINEAGE_API = env.LINEAGE_API ?? "http://localhost:8001";

const proxy: RequestHandler = async ({ url, fetch, request, locals }) => {
	const target = LINEAGE_API + url.pathname.replace(/^\/api/, "") + url.search;
	// Forward the signed-in user's access token as a bearer so the lineage service can verify + authorize
	// (when its OIDC/FGA are on). No session → no header, so the demo's auth-OFF mode is unchanged.
	const headers: Record<string, string> = {};
	if (locals.session) headers["authorization"] = `Bearer ${locals.session.accessToken}`;
	const init: RequestInit =
		request.method === "GET" || request.method === "HEAD"
			? { method: request.method, headers }
			: {
					method: request.method,
					headers: {
						...headers,
						"content-type": request.headers.get("content-type") ?? "application/json",
					},
					body: await request.text(),
				};
	try {
		const upstream = await fetch(target, init);
		return new Response(upstream.body, {
			status: upstream.status,
			headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
		});
	} catch (err) {
		return new Response(JSON.stringify({ error: String(err) }), {
			status: 502,
			headers: { "content-type": "application/json" },
		});
	}
};

export const GET = proxy;
export const POST = proxy;
