import { env } from "$env/dynamic/private";
import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

const CATALOG_API = env.CATALOG_API ?? "http://localhost:2333";

// The ONE catalog write the UI performs, deliberately its own narrow route instead of a POST on the
// generic /capi proxy: a promote carries ONLY the signed-in user's bearer — never any service
// credential — so the catalog's validator rung (can_promote) is enforced against a real user, and an
// anonymous visitor is refused HERE without the request ever leaving the BFF (the same confused-deputy
// stance that keeps the /api lineage proxy GET-only, bug hunt 2026-07-13).
export const POST: RequestHandler = async ({ params, request, fetch, locals }) => {
	if (!locals.session) {
		return json({ detail: "sign in to promote a model" }, { status: 401 });
	}
	const target = `${CATALOG_API}/v1/model/${encodeURIComponent(params.model)}/promote`;
	try {
		const upstream = await fetch(target, {
			method: "POST",
			headers: {
				authorization: `Bearer ${locals.session.accessToken}`,
				"content-type": request.headers.get("content-type") ?? "application/json",
			},
			body: await request.text(),
		});
		return new Response(upstream.body, {
			status: upstream.status,
			headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
		});
	} catch (err) {
		return json({ detail: String(err) }, { status: 502 });
	}
};
