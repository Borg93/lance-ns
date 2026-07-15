import { env } from "$env/dynamic/private";
import type { RequestHandler } from "./$types";

// Same-origin proxy to the CATALOG service (the /api proxy covers lineage). The catalog is OIDC-only —
// it has NO service-token door (unlike the lineage ingest) — so the only credential ever attached is the
// signed-in user's bearer. No session → no header: the auth-off dev stack answers openly; a governed
// stack answers 401 and the models page renders its sign-in state instead of data.
const CATALOG_API = env.CATALOG_API ?? "http://localhost:2333";

const proxy: RequestHandler = async ({ url, fetch, locals }) => {
	const target = CATALOG_API + url.pathname.replace(/^\/capi/, "") + url.search;
	const headers: Record<string, string> = {};
	if (locals.session) {
		headers["authorization"] = `Bearer ${locals.session.accessToken}`;
	}
	try {
		const upstream = await fetch(target, { method: "GET", headers });
		return new Response(upstream.body, {
			status: upstream.status,
			headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
		});
	} catch (err) {
		return new Response(JSON.stringify({ detail: String(err) }), {
			status: 502,
			headers: { "content-type": "application/json" },
		});
	}
};

// GET only — same confused-deputy stance as the /api BFF (bug hunt 2026-07-13): no blanket write proxy.
// The single catalog write the UI performs (model promote) has its own narrow session-required route at
// capi/v1/model/[model]/promote, so an anonymous visitor can never reach a mutating catalog endpoint.
export const GET = proxy;
