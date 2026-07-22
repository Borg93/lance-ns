import { test, expect } from '@playwright/test';

// The home zone owns the relocated OIDC BFF routes (/auth/{login,callback,logout}). Running auth-OFF (no
// OIDC env), the routes must exist and FAIL SAFE — login/logout are no-op redirects home, never 404s or
// 500s — and the landing must show no auth affordance. This proves the P2→P5 relocation landed (the routes
// left apps/web and live in the home catch-all) without needing a live Dex. The real per-user round-trip
// (login → Dex → callback → sealed cookie → cross-zone session) is the live P5 drive.

test('GET /auth/login is a fail-safe no-op redirect home when auth is unconfigured', async ({
	page,
	baseURL,
}) => {
	// The route EXISTS in the home zone (not a 404) and, auth-off, redirects home rather than erroring or
	// starting a flow against a missing IdP. Following the 302 lands on the home landing.
	const res = await page.goto('/auth/login');
	expect(res?.status()).toBe(200); // followed the 302 → the landing rendered (not a 404/500)
	expect(page.url()).toBe(`${baseURL}/`);
	await expect(page.getByRole('heading', { name: 'lance', exact: true })).toBeVisible();
});

test('GET /auth/logout clears the session and redirects home', async ({ page, baseURL }) => {
	const res = await page.goto('/auth/logout');
	expect(res?.status()).toBe(200);
	expect(page.url()).toBe(`${baseURL}/`);
});

test('the landing lists the four zones and shows NO auth control when auth is off', async ({
	page,
}) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'lance', exact: true })).toBeVisible();
	for (const zone of ['Data', 'Lineage', 'Models', 'Admin']) {
		await expect(page.getByRole('link', { name: new RegExp(zone) }).first()).toBeVisible();
	}
	// authEnabled is false → the sign-in affordance is gated off entirely (no dead login link on an ungoverned stack).
	await expect(page.getByRole('link', { name: 'Sign out' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Sign in' })).toHaveCount(0);
});
