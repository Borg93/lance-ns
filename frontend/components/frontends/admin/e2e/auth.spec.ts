import { test, expect } from '@playwright/test';

// The shared cross-zone auth affordance (P5 "auth in every MFE"). This suite runs the admin zone with OIDC
// CONFIGURED (playwright.config.ts webServer.env) but with NO session, so the shell is in the signed-out
// state. It asserts (1) the shared nav-user renders the signed-out "Sign in" identity — i.e. authEnabled
// (from the per-zone +layout.server.ts) drives the affordance — and (2) that /auth/* is NOT in a domain
// zone (the home zone owns it), so a direct hit 404s. The exact login LINK (href + data-sveltekit-reload)
// lives in the portalled dropdown; it's pinned by the @rask/ui build + the home-zone route tests rather
// than by driving a flaky headless dropdown, and the live cross-zone round-trip is the P5 drive.

test('signed-out: the shared nav-user shows the "Sign in" identity when auth is enabled', async ({
	page,
}) => {
	await page.goto('/admin/audit');
	await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();
	// The footer profile trigger renders the signed-out identity ("Sign in" / "not signed in") — proof that
	// authEnabled flowed session→user→AppShell→nav-user and selected the signed-out branch.
	await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible();
});

test('/auth was relocated OUT of the domain zones — the home zone owns it (admin 404s)', async ({
	page,
}) => {
	// A direct hit on the login route inside the isolated admin dev server 404s: only the home zone serves
	// /auth/*. The gateway path-routes /auth → home in the composed deployment (P5 chart).
	const res = await page.goto('/admin/auth/login');
	expect(res?.status()).toBe(404);
});
