// @rask/api/bff — the SvelteKit BFF integration for the OIDC seam (server-only). Env-free: each app
// passes its own $env values in, so this is the shared, single-sourced auth trailer (mirroring the
// backend services' shared auth). Imports @sveltejs/kit TYPES only, so it lives in server bundles.
import type { Handle, RequestHandler } from '@sveltejs/kit';
import {
	SESSION_COOKIE,
	decodeSession,
	deriveSessionKey,
	isExpired,
	type OidcConfig,
	type Session,
} from './oidc';

type Env = Record<string, string | undefined>;

/** The identity the shared AppShell's nav-user renders — structurally the `@rask/ui` shell's `NavUser`
 *  (name/email/initials), produced here (the data seam) and consumed there (the view), no cross-package dep. */
export interface SessionUser {
	name: string;
	email?: string;
	initials?: string;
}

/** Up-to-two-letter initials for the avatar fallback: first letter of the first two words, else the first
 *  two characters — always uppercased. */
function initialsOf(name: string): string {
	const words = name.trim().split(/\s+/).filter(Boolean);
	const letters =
		words.length >= 2 ? words[0]![0]! + words[1]![0]! : (words[0] ?? name).slice(0, 2);
	return letters.toUpperCase();
}

/** Project the OIDC session onto the shell identity, or `null` when signed out. Single-sourced so every
 *  zone's `+layout.server.ts` derives the same `user` — the "auth is identical in every MFE" seam. */
export function sessionToUser(session: Session | null): SessionUser | null {
	if (!session) return null;
	const name = session.name || session.email || session.sub;
	const user: SessionUser = { name, initials: initialsOf(name) };
	// exactOptionalPropertyTypes: only set `email` when present (never assign an explicit undefined).
	if (session.email) user.email = session.email;
	return user;
}

/** The auth fields the shared handle/proxy read on `event.locals`. Each zone's `app.d.ts` declares
 *  `interface Locals extends AuthLocals {}` so its RequestEvent carries them. */
export interface AuthLocals {
	session: Session | null;
	authEnabled: boolean;
}

/** Build the OIDC config from a plain env record, or `null` when unconfigured (→ the zone runs auth-OFF).
 *  Server-only (derives the AES key via node:crypto). */
export function makeOidcConfig(env: Env): OidcConfig | null {
	const issuer = env.OIDC_ISSUER;
	const clientId = env.OIDC_CLIENT_ID;
	const redirectUri = env.OIDC_REDIRECT_URI;
	if (!issuer || !clientId || !redirectUri) return null;
	return {
		issuer: issuer.replace(/\/$/, ''),
		clientId,
		clientSecret: env.OIDC_CLIENT_SECRET || null,
		redirectUri,
		scopes: env.OIDC_SCOPES || 'openid profile email',
		// SESSION_SECRET seals the cookie (AES-256-GCM); unset in dev → unsealed base64 (documented).
		sessionKey: env.SESSION_SECRET ? deriveSessionKey(env.SESSION_SECRET) : null,
		// Split-horizon: server-side fetches (discovery, token POST) go here when set — the in-cluster Dex
		// Service — while the browser's authorize redirect + iss keep the public OIDC_ISSUER above.
		internalIssuer: env.OIDC_INTERNAL_ISSUER?.replace(/\/$/, '') || null,
	};
}

/** Per-request `handle`: hydrate `locals.session` from the sealed cookie, dropping a stale/dead one so a
 *  dead token is never forwarded. No-op when `cfg` is null (auth off). Single-sourced so every zone shares
 *  identical session semantics. */
export function makeSessionHandle(cfg: OidcConfig | null): Handle {
	return async ({ event, resolve }) => {
		// App.Locals is declared per-zone; in @rask/api's own typecheck it's empty, so read via AuthLocals.
		const locals = event.locals as unknown as AuthLocals;
		locals.authEnabled = cfg !== null;
		locals.session = null;
		const raw = event.cookies.get(SESSION_COOKIE);
		if (cfg && raw) {
			const session = decodeSession(raw, cfg.sessionKey);
			if (session && !isExpired(session, Math.floor(Date.now() / 1000))) {
				locals.session = session;
			} else {
				event.cookies.delete(SESSION_COOKIE, { path: '/' });
			}
		}
		return resolve(event);
	};
}

/** A same-origin backend-proxy `RequestHandler` factory. Forwards the signed-in user's access token as a
 *  bearer (so the backend verifies + FGA-authorizes the call); a READ-only service-credential fallback lets
 *  a governed stack serve reads without a per-user login — NEVER on writes (the confused-deputy guard). */
export function makeBackendProxy(opts: {
	backendUrl: string;
	stripPrefix: RegExp;
	serviceToken?: string | undefined;
	serviceId?: string | undefined;
}): RequestHandler {
	return async ({ url, fetch, request, locals }) => {
		const target = opts.backendUrl + url.pathname.replace(opts.stripPrefix, '') + url.search;
		const isRead = request.method === 'GET' || request.method === 'HEAD';
		const headers: Record<string, string> = {};
		const session = (locals as unknown as AuthLocals).session;
		if (session) {
			headers['authorization'] = `Bearer ${session.accessToken}`;
		} else if (opts.serviceToken && isRead) {
			headers['dapr-api-token'] = opts.serviceToken;
			headers['x-lance-service-identity'] = opts.serviceId ?? '';
		}
		const init: RequestInit = isRead
			? { method: request.method, headers }
			: {
					method: request.method,
					headers: {
						...headers,
						'content-type': request.headers.get('content-type') ?? 'application/json',
					},
					body: await request.text(),
				};
		try {
			const upstream = await fetch(target, init);
			return new Response(upstream.body, {
				status: upstream.status,
				headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json' },
			});
		} catch (err) {
			return new Response(JSON.stringify({ error: String(err) }), {
				status: 502,
				headers: { 'content-type': 'application/json' },
			});
		}
	};
}
