/**
 * OIDC Authorization-Code-+-PKCE flow for the SvelteKit BFF (server-only).
 *
 * The demo UI runs auth-OFF by default (the backend's enforcement ships default-OFF too); set
 * `OIDC_ISSUER` + `OIDC_CLIENT_ID` (+ `OIDC_REDIRECT_URI`) to turn it on against Dex. When on, the
 * browser signs in at Dex, this BFF holds the tokens in an httpOnly session cookie, and the API proxy
 * forwards the access token as a bearer so the lineage service can verify + authorize the call.
 *
 * Lives under `$lib/server/` so SvelteKit guarantees it never ships to the browser. The pure + network
 * helpers live in `./oidc-core` (no `$env` import, so they're unit-tested under `bun test`); this module
 * adds only `oidcConfig()`, which reads `$env`, and re-exports the rest.
 *
 * Session cookie: httpOnly + sameSite so the browser can't read it and XSS can't exfiltrate it, and — when
 * `SESSION_SECRET` is set — SEALED with AES-256-GCM (`v1.` prefix, tamper-evident) via `encodeSession` /
 * `decodeSession` in `./oidc-core`. Unset in dev → an unsealed base64 cookie (documented). The one
 * demo-grade limitation that remains is no refresh-token rotation (the cookie lifetime is bounded to the
 * id_token's exp; the session dies with the token).
 */
import { env } from "$env/dynamic/private";

import { deriveSessionKey, type OidcConfig } from "./oidc-core";

export * from "./oidc-core";

/** The OIDC config from env, or `null` when unconfigured (→ the demo runs auth-OFF). */
export function oidcConfig(): OidcConfig | null {
	const issuer = env.OIDC_ISSUER;
	const clientId = env.OIDC_CLIENT_ID;
	const redirectUri = env.OIDC_REDIRECT_URI;
	if (!issuer || !clientId || !redirectUri) return null;
	return {
		issuer: issuer.replace(/\/$/, ""),
		clientId,
		clientSecret: env.OIDC_CLIENT_SECRET || null,
		redirectUri,
		scopes: env.OIDC_SCOPES || "openid profile email",
		// SESSION_SECRET seals the session cookie (AES-256-GCM). Unset in dev → base64 (unsealed, documented);
		// production sets it so a forged cookie can't impersonate a user.
		sessionKey: env.SESSION_SECRET ? deriveSessionKey(env.SESSION_SECRET) : null,
	};
}
