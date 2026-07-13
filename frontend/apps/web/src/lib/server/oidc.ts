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
 * Demo-grade session: the cookie is httpOnly + sameSite so the browser can't read it and XSS can't
 * exfiltrate it, but it is NOT encrypted/signed — a production BFF would seal it (e.g. AES-GCM with a
 * server key) and add refresh-token rotation. Documented, not hidden.
 */
import { env } from "$env/dynamic/private";

import type { OidcConfig } from "./oidc-core";

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
	};
}
