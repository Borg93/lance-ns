/**
 * Pure + network OIDC helpers, with NO SvelteKit (`$env`) import, so they run under `bun test`.
 * `oidc.ts` re-exports everything here and adds only `oidcConfig()` (which reads `$env`).
 *
 * The pure pieces (PKCE, state, authorize-URL, token-request body, JWT-claims decode, session codec)
 * are unit-tested in `oidc-core.test.ts`; `discover` / `exchangeCode` take an injectable `fetch` so the
 * exchange is testable against a fake token endpoint too.
 */

export const SESSION_COOKIE = "lance_session";
export const VERIFIER_COOKIE = "oidc_verifier";
export const STATE_COOKIE = "oidc_state";

export type OidcConfig = {
	issuer: string;
	clientId: string;
	clientSecret: string | null;
	redirectUri: string;
	scopes: string;
};

export type Session = {
	sub: string;
	name: string;
	email: string | null;
	accessToken: string;
	expiresAt: number; // epoch seconds
};

/** RFC 4648 §5 base64url (no padding) of raw bytes. */
export function base64url(bytes: Uint8Array): string {
	let bin = "";
	for (const b of bytes) bin += String.fromCharCode(b);
	return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decode a base64url string back to UTF-8 text (restores padding first). */
export function base64urlDecode(s: string): string {
	const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
	const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
	const bin = atob(padded);
	return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

/** A cryptographically-random base64url token (the PKCE verifier / the CSRF state). */
export function randomToken(bytes = 32): string {
	return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** The PKCE S256 challenge for a verifier: base64url(SHA-256(verifier)). */
export async function pkceChallenge(verifier: string): Promise<string> {
	const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
	return base64url(new Uint8Array(digest));
}

/** The Dex authorize URL the browser is redirected to (PKCE S256, CSRF state). */
export function buildAuthorizeUrl(
	cfg: OidcConfig,
	authorizationEndpoint: string,
	state: string,
	challenge: string,
): string {
	const url = new URL(authorizationEndpoint);
	url.searchParams.set("response_type", "code");
	url.searchParams.set("client_id", cfg.clientId);
	url.searchParams.set("redirect_uri", cfg.redirectUri);
	url.searchParams.set("scope", cfg.scopes);
	url.searchParams.set("state", state);
	url.searchParams.set("code_challenge", challenge);
	url.searchParams.set("code_challenge_method", "S256");
	return url.toString();
}

/** The url-encoded body for the authorization-code token exchange. */
export function tokenRequestBody(cfg: OidcConfig, code: string, verifier: string): URLSearchParams {
	const body = new URLSearchParams({
		grant_type: "authorization_code",
		code,
		redirect_uri: cfg.redirectUri,
		client_id: cfg.clientId,
		code_verifier: verifier,
	});
	if (cfg.clientSecret) body.set("client_secret", cfg.clientSecret);
	return body;
}

/** Decode (NOT verify) a JWT's claims — trusted because it came straight from the token endpoint over TLS. */
export function decodeJwtClaims(jwt: string): Record<string, unknown> {
	const payload = jwt.split(".")[1];
	if (!payload) throw new Error("malformed JWT");
	return JSON.parse(base64urlDecode(payload));
}

/** Build the session from a token response's id_token + access_token. */
export function sessionFromTokens(idToken: string, accessToken: string): Session {
	const claims = decodeJwtClaims(idToken);
	const exp = typeof claims.exp === "number" ? claims.exp : 0;
	return {
		sub: String(claims.sub ?? ""),
		name: String(claims.name ?? claims.preferred_username ?? claims.email ?? claims.sub ?? "user"),
		email: typeof claims.email === "string" ? claims.email : null,
		accessToken,
		expiresAt: exp,
	};
}

/** Serialize / parse the session for the httpOnly cookie (base64url JSON — see oidc.ts header on sealing). */
export function encodeSession(session: Session): string {
	return base64url(new TextEncoder().encode(JSON.stringify(session)));
}

export function decodeSession(raw: string): Session | null {
	try {
		const obj = JSON.parse(base64urlDecode(raw)) as Session;
		if (!obj.sub || !obj.accessToken) return null;
		return obj;
	} catch {
		return null;
	}
}

/** Has the session's access token expired? (0 = no expiry claim → treat as live for the demo.) */
export function isExpired(session: Session, nowSeconds: number): boolean {
	return session.expiresAt > 0 && session.expiresAt <= nowSeconds;
}

type Discovery = {
	authorization_endpoint: string;
	token_endpoint: string;
	end_session_endpoint?: string;
};

/** Fetch the OIDC discovery document (`/.well-known/openid-configuration`). */
export async function discover(cfg: OidcConfig, fetchFn: typeof fetch = fetch): Promise<Discovery> {
	const res = await fetchFn(`${cfg.issuer}/.well-known/openid-configuration`);
	if (!res.ok) throw new Error(`OIDC discovery failed: ${res.status}`);
	return (await res.json()) as Discovery;
}

/** Exchange an authorization code (+ PKCE verifier) for tokens, returning the session. */
export async function exchangeCode(
	cfg: OidcConfig,
	tokenEndpoint: string,
	code: string,
	verifier: string,
	fetchFn: typeof fetch = fetch,
): Promise<Session> {
	const res = await fetchFn(tokenEndpoint, {
		method: "POST",
		headers: { "content-type": "application/x-www-form-urlencoded" },
		body: tokenRequestBody(cfg, code, verifier),
	});
	if (!res.ok) throw new Error(`token exchange failed: ${res.status}`);
	const tokens = (await res.json()) as { access_token: string; id_token: string };
	return sessionFromTokens(tokens.id_token, tokens.access_token);
}
