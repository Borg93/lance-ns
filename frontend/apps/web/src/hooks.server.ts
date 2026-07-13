/**
 * Per-request auth: hydrate `locals.session` from the httpOnly session cookie so server routes (the API
 * proxy) and `+layout.server.ts` can see who's signed in. No-op when OIDC is unconfigured — the demo
 * then runs auth-OFF exactly as before. An expired session is cleared so a stale token is never forwarded.
 */
import type { Handle } from "@sveltejs/kit";
import { SESSION_COOKIE, decodeSession, isExpired, oidcConfig } from "$lib/server/oidc";

export const handle: Handle = async ({ event, resolve }) => {
	const authEnabled = oidcConfig() !== null;
	event.locals.authEnabled = authEnabled;
	event.locals.session = null;

	const raw = event.cookies.get(SESSION_COOKIE);
	if (authEnabled && raw) {
		const session = decodeSession(raw);
		if (session && !isExpired(session, Math.floor(Date.now() / 1000))) {
			event.locals.session = session;
		} else {
			// Malformed or expired → drop it so we never forward a dead token.
			event.cookies.delete(SESSION_COOKIE, { path: "/" });
		}
	}

	return resolve(event);
};
