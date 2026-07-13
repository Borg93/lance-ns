import { env } from "$env/dynamic/private";
import type { RequestHandler } from "./$types";

// Same-origin proxy to the lineage service so the browser never needs CORS. In compose this points
// at the in-cluster service (LINEAGE_API=http://lineage-api:8000); locally it defaults to :8001.
const LINEAGE_API = env.LINEAGE_API ?? "http://localhost:8001";

const proxy: RequestHandler = async ({ url, fetch, request, locals }) => {
	const target = LINEAGE_API + url.pathname.replace(/^\/api/, "") + url.search;
	// Forward the signed-in user's access token as a bearer so the lineage service can verify + authorize
	// (when its OIDC/FGA are on). No session → no header, so the demo's auth-OFF mode is unchanged.
	// Fallback: when no user is signed in but a SERVICE credential is configured, authenticate to lineage
	// as an in-cluster service via the app-token door (the same one the Ray trainer uses) — so the
	// read-only lineage UI works on a GOVERNED (auth-on) stack without a per-user browser login, bounded
	// by the service subject's FGA reader rung. Gated on LINEAGE_SERVICE_TOKEN so it's a no-op when unset.
	const isRead = request.method === "GET" || request.method === "HEAD";
	const headers: Record<string, string> = {};
	if (locals.session) {
		headers["authorization"] = `Bearer ${locals.session.accessToken}`;
	} else if (env.LINEAGE_SERVICE_TOKEN && isRead) {
		// READ-only: attach the in-cluster service credential ONLY for safe methods. Attaching it to a
		// write would turn the read-only BFF into an UNAUTHENTICATED writer into the governed lineage
		// audit graph as `service-web` (a confused-deputy hole found by the 2026-07-13 bug hunt).
		headers["dapr-api-token"] = env.LINEAGE_SERVICE_TOKEN;
		headers["x-lance-service-identity"] = env.LINEAGE_SERVICE_ID ?? "";
	}
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

// GET/HEAD only — the lineage UI is read-only. POST is deliberately NOT exported: exposing it would let
// an anonymous visitor forge writes into the governed audit graph via the service credential (bug hunt
// 2026-07-13). The Ray trainer POSTs to lineage directly, not through this BFF.
export const GET = proxy;
