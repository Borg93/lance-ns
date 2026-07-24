import type { BrowserContext } from '@playwright/test';

// Sign the e2e browser context in. The admin dev server runs auth-ON (OIDC env in playwright.config.ts),
// and the login-first gate now redirects a signed-out page navigation to /auth/login — owned by the home
// zone, so absent in this isolated server. The panel specs therefore run SIGNED-IN: the server has no
// SESSION_SECRET, so the BFF accepts the documented dev-grade UNSEALED base64url session cookie, which we
// mint here. The signed-out redirect contract itself is pinned by auth.spec.ts.
const SESSION = {
	sub: 'user:e2e',
	name: 'E2E Admin',
	email: 'e2e@example.com',
	accessToken: 'e2e-token',
	expiresAt: 0, // no expiry claim → treated live
};

/** The display name the shared nav-user renders for the minted session (auth.spec.ts asserts it). */
export const SESSION_NAME = SESSION.name;

export async function signIn(context: BrowserContext, origin = 'http://localhost:5295') {
	const value = Buffer.from(JSON.stringify(SESSION), 'utf8')
		.toString('base64')
		.replace(/\+/g, '-')
		.replace(/\//g, '_')
		.replace(/=+$/, '');
	await context.addCookies([{ name: 'lance_session', value, url: origin, httpOnly: true }]);
}
