import type { BrowserContext, Page } from '@playwright/test';
import { AUTH_ON } from '../ports';

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

// The frozen /v1/me shapes the layout door + navbar read (mocked at the browser boundary — the
// layout fetches me through this zone's /capi/v1/me pass-through, so page.route can intercept it).
export const ME_ADMIN = {
	sub: 'user:e2e',
	name: 'E2E Admin',
	email: 'e2e@example.com',
	estate_admin: true,
	projects: [{ project: 'acme', role: 'admin' }],
};

/** A bob-shaped identity: verified, but WITHOUT the estate-admin privilege — the admin zone's
 *  layout-level door must answer ForbiddenPage and the navbar must hide Admin + Access. */
export const ME_MEMBER = {
	sub: 'user:bob',
	name: 'Bob',
	email: 'bob@example.com',
	estate_admin: false,
	projects: [{ project: 'acme', role: 'member' }],
};

/** Mock the zone's /capi/v1/me pass-through (default: an estate admin, so panels render). */
export async function mockMe(page: Page, me: unknown = ME_ADMIN) {
	await page.route('**/capi/v1/me', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(me) }),
	);
}

export async function signIn(context: BrowserContext, origin = AUTH_ON) {
	const value = Buffer.from(JSON.stringify(SESSION), 'utf8')
		.toString('base64')
		.replace(/\+/g, '-')
		.replace(/\//g, '_')
		.replace(/=+$/, '');
	await context.addCookies([{ name: 'lance_session', value, url: origin, httpOnly: true }]);
}
