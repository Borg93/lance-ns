/**
 * Start the OIDC login: mint a PKCE verifier + CSRF state, stash them in short-lived httpOnly cookies,
 * and redirect the browser to Dex's authorize endpoint. No-op redirect home when auth is unconfigured.
 */
import { redirect, type RequestHandler } from "@sveltejs/kit";
import {
	STATE_COOKIE,
	VERIFIER_COOKIE,
	buildAuthorizeUrl,
	discover,
	oidcConfig,
	pkceChallenge,
	randomToken,
} from "$lib/server/oidc";

const TEMP_COOKIE_MAX_AGE = 600; // 10 min — long enough to complete the round-trip to Dex.

export const GET: RequestHandler = async ({ cookies, fetch }) => {
	const cfg = oidcConfig();
	if (!cfg) redirect(302, "/");

	const verifier = randomToken();
	const state = randomToken(16);
	const challenge = await pkceChallenge(verifier);
	const opts = { path: "/", httpOnly: true, sameSite: "lax", maxAge: TEMP_COOKIE_MAX_AGE } as const;
	cookies.set(VERIFIER_COOKIE, verifier, opts);
	cookies.set(STATE_COOKIE, state, opts);

	const { authorization_endpoint } = await discover(cfg, fetch);
	redirect(302, buildAuthorizeUrl(cfg, authorization_endpoint, state, challenge));
};
