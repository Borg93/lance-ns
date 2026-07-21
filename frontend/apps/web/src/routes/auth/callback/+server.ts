/**
 * OIDC redirect target: verify the CSRF state against the cookie, exchange the code (+ PKCE verifier)
 * for tokens, and seal the resulting session into an httpOnly cookie. The temp PKCE/state cookies are
 * cleared either way. Any failure redirects home with `?auth=error` rather than leaking details.
 */
import { redirect, type RequestHandler } from "@sveltejs/kit";
import {
	SESSION_COOKIE,
	STATE_COOKIE,
	VERIFIER_COOKIE,
	discover,
	encodeSession,
	exchangeCode,
	oidcConfig,
} from "$lib/server/oidc";

export const GET: RequestHandler = async ({ url, cookies, fetch }) => {
	const cfg = oidcConfig();
	const verifier = cookies.get(VERIFIER_COOKIE);
	const expectedState = cookies.get(STATE_COOKIE);
	cookies.delete(VERIFIER_COOKIE, { path: "/" });
	cookies.delete(STATE_COOKIE, { path: "/" });

	const code = url.searchParams.get("code");
	const state = url.searchParams.get("state");
	// Fail closed on any precondition: missing config, no code, or a state/verifier that doesn't match
	// (the CSRF guard — an attacker-forged callback can't carry our one-time state).
	if (!cfg || !code || !state || !verifier || state !== expectedState) {
		redirect(302, "/?auth=error");
	}

	try {
		const { token_endpoint } = await discover(cfg, fetch);
		const session = await exchangeCode(cfg, token_endpoint, code, verifier, fetch);
		cookies.set(SESSION_COOKIE, encodeSession(session, cfg.sessionKey), {
			path: "/",
			httpOnly: true,
			sameSite: "lax",
			// Bound the cookie lifetime to the token's, when known (else a session-cookie that dies with the browser).
			maxAge:
				session.expiresAt > 0
					? Math.max(0, session.expiresAt - Math.floor(Date.now() / 1000))
					: undefined,
		});
	} catch {
		redirect(302, "/?auth=error");
	}
	redirect(302, "/");
};
