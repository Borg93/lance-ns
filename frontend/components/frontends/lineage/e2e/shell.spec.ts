import { test, expect, type Route } from '@playwright/test';

// The estate shell in the LINEAGE zone: the cross-zone TopNavbar fed by a mocked /v1/me (hermetic —
// the layout fetches it through this zone's /capi/v1/me pass-through), and the zone-scoped sidebar
// carrying exactly this zone's views: Datasets / Jobs / Runs / Columns + the Graph at the root.

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

test('an estate admin gets the full navbar entry set + the Marquez-parity sidebar leaves', async ({
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
	// The zone sidebar lists exactly the four first-class views + the Graph (active at the root).
	// Scoped to the sidebar: page content may legitimately link to the same views (e.g. the graph
	// header's capped hint links to Datasets), which would trip strict mode on a page-wide query.
	const sidebar = page.locator('[data-sidebar="content"]');
	for (const leaf of ['Datasets', 'Jobs', 'Runs', 'Columns', 'Graph']) {
		await expect(sidebar.getByRole('link', { name: leaf, exact: true })).toBeVisible();
	}
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Graph' })).toBeVisible();
});

test('the Datasets leaf lights on its list page and stays lit on a nested detail page', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/lineage/datasets');
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Datasets' })).toBeVisible();
	await page.goto('/lineage/datasets/silver%24features');
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Datasets' })).toBeVisible();
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
