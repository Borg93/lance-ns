import { test, expect } from '@playwright/test';

// The home zone owns the relocated OIDC BFF routes (/auth/{login,callback,logout}) AND the
// signed-in landing (navbar + project gallery). Running auth-OFF (no OIDC env, no catalog), the
// routes must exist and FAIL SAFE — login/logout are no-op redirects home, never 404s or 500s —
// and the landing must show no auth affordance, the base navbar (no estate-admin entries: fetchMe
// resolves null), and the gallery's empty state. The real per-user round-trip (login → Dex →
// callback → sealed cookie → cross-zone session) is the live P5 drive.

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

test('the navbar lists the base zones and hides the estate-admin entries for an anonymous visitor', async ({
	page,
}) => {
	await page.goto('/');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav).toBeVisible();
	for (const zone of ['Home', 'Data', 'Lineage', 'Models', 'Media', 'Annotator']) {
		await expect(nav.getByRole('link', { name: zone, exact: true })).toBeVisible();
	}
	// fetchMe resolves null (no session, no catalog) → estate_admin is unknowable → fail-closed.
	await expect(nav.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0);
	await expect(nav.getByRole('link', { name: 'Access', exact: true })).toHaveCount(0);
	// Cross-zone navbar links hard-navigate out of the home zone's route manifest.
	await expect(nav.getByRole('link', { name: 'Data', exact: true })).toHaveAttribute(
		'data-sveltekit-reload',
		'',
	);
});

test('the landing shows the gallery empty state and NO auth control when auth is off', async ({
	page,
}) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'lance', exact: true })).toBeVisible();
	// Auth-off + no catalog → signed out, no projects → the empty state names the unconfigured sign-in.
	await expect(page.getByText('sign-in is not configured on this stack')).toBeVisible();
	// authEnabled is false → the sign-in affordance is gated off entirely (no dead login link on an
	// ungoverned stack) — neither the gallery prompt nor a navbar menu entry.
	await expect(page.getByRole('link', { name: 'Sign out' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Sign in' })).toHaveCount(0);
	await expect(page.getByRole('link', { name: 'Sign in' })).toHaveCount(0);
});
