import { test, expect, type Route } from '@playwright/test';

// The estate shell in the LINEAGE zone: the cross-zone TopNavbar fed by a mocked /v1/me (hermetic —
// the layout fetches it through this zone's /capi/v1/me pass-through), and the zone-scoped sidebar
// carrying ONLY this zone's own route (the explorer graph).

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

test.beforeEach(async ({ page }) => {
	// The explorer's own backend calls — empty world is fine for shell assertions.
	await page.route('**/lineage/api/**', (route) => json(route, {}));
	await page.route('**/lineage/capi/**', (route) => {
		const path = new URL(route.request().url()).pathname;
		if (path.endsWith('/v1/me')) return route.fallback();
		return json(route, {});
	});
});

test('an estate admin gets the full navbar entry set + the Graph sidebar leaf', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) =>
		json(route, {
			sub: 'user:alice',
			name: 'Alice',
			email: 'alice@example.com',
			estate_admin: true,
			projects: [{ project: 'acme', role: 'admin' }],
		}),
	);
	await page.goto('/lineage');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Lineage' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Admin' })).toBeVisible();
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Graph' })).toBeVisible();
});

test('a signed-out / unresolved identity renders the base entries only (fail-closed)', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/lineage');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Data' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0);
});
