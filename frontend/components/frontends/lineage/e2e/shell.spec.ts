import { test, expect, type Route } from '@playwright/test';

// The estate shell in the LINEAGE zone: the cross-zone TopNavbar fed by a mocked /v1/me (hermetic —
// the layout fetches it through this zone's /capi/v1/me pass-through), the zone-scoped sidebar
// carrying exactly this zone's views (Datasets / Jobs / Runs / Columns + the Graph at the root), and
// the two-row header — navbar row above, breadcrumb bar below.

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
	// Lineage and Admin both carry sub-areas, so they are NavigationMenu triggers, not links.
	await expect(nav.getByRole('button', { name: 'Lineage', exact: true })).toBeVisible();
	await expect(nav.getByRole('button', { name: 'Admin', exact: true })).toBeVisible();
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
	await expect(nav.getByRole('button', { name: 'Data', exact: true })).toBeVisible();
	await expect(nav.getByRole('button', { name: 'Admin', exact: true })).toHaveCount(0);
	await expect(nav.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0);
});

test('a zone with sub-areas opens a panel of them — pointer and keyboard, cross-zone rows reloading', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/lineage');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	const data = nav.getByRole('button', { name: 'Data', exact: true });
	const panel = page.locator('[data-slot="navigation-menu-viewport"]');
	// Closed by default: the panel's rows are not in the document at all (nothing to tab into).
	await expect(panel).toHaveCount(0);

	await data.click();
	await expect(panel).toBeVisible();
	for (const row of ['Projects', 'Tables', 'Namespaces', 'Warehouses']) {
		await expect(panel.getByRole('link', { name: new RegExp(`^${row}`) })).toBeVisible();
	}
	// Each row leaves THIS zone's route manifest, so it must hard-navigate…
	await expect(panel.locator('a[href="/data/tables"]')).toHaveAttribute(
		'data-sveltekit-reload',
		'',
	);
	// …and the zone root stays reachable, because the trigger itself is a button, not a link. Data
	// has no row at /data, so the panel adds the root row — exactly one of it.
	await expect(panel.locator('a[href="/data"]')).toHaveCount(1);

	// Escape closes it, and the trigger is still the focused element.
	await page.keyboard.press('Escape');
	await expect(panel).toBeHidden();
	// Keyboard-only open: focus the trigger and press Enter.
	await data.focus();
	await page.keyboard.press('Enter');
	await expect(page.locator('[data-slot="navigation-menu-viewport"]')).toBeVisible();
});

test('the loading skeleton reserves the resolved entry widths — no shift when /v1/me lands', async ({
	page,
}) => {
	// The 4b2af0e no-CLS contract, re-proven against the NavigationMenu chrome: the skeleton pills
	// must reserve the resolved entries' exact box, chevrons included, so the navbar does not jump
	// when the identity resolves. Held open until the loading geometry has been measured.
	let release = () => {};
	const gate = new Promise<void>((resolve) => (release = resolve));
	await page.route('**/capi/v1/me', async (route) => {
		await gate;
		return json(route, { detail: 'anon' }, 401);
	});
	await page.goto('/lineage');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.locator('[data-slot="skeleton"]').first()).toBeVisible();
	const loading = (await nav.boundingBox())!;

	release();
	await expect(nav.getByRole('link', { name: 'Home', exact: true })).toBeVisible();
	const resolved = (await nav.boundingBox())!;
	expect(Math.abs(resolved.width - loading.width)).toBeLessThanOrEqual(1);
	expect(Math.abs(resolved.x - loading.x)).toBeLessThanOrEqual(1);
});

test('the breadcrumb bar is its OWN row below the zone links — never overlapping, even narrow', async ({
	page,
}) => {
	// The regression this guards: both used to share one header row, so on a narrow viewport the
	// trail and the zone links collided. Geometry, not markup: the breadcrumb row must start at or
	// below the navbar row's bottom edge, and the two must not intersect vertically.
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.setViewportSize({ width: 820, height: 800 });
	await page.goto('/lineage/datasets');
	const zones = page.getByRole('navigation', { name: 'Zones' });
	const trail = page.getByRole('navigation', { name: 'Breadcrumb' });
	await expect(zones).toBeVisible();
	await expect(trail).toBeVisible();
	const zonesBox = (await zones.boundingBox())!;
	const trailBox = (await trail.boundingBox())!;
	expect(trailBox.y).toBeGreaterThanOrEqual(zonesBox.y + zonesBox.height - 1);
	// …and neither row overflows the viewport horizontally.
	expect(zonesBox.x + zonesBox.width).toBeLessThanOrEqual(820);
	expect(trailBox.x + trailBox.width).toBeLessThanOrEqual(820);
});

test('the breadcrumb trail links back up the path and marks the current page', async ({ page }) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/lineage/datasets/silver%24features');
	const trail = page.getByRole('navigation', { name: 'Breadcrumb' });
	// Every crumb but the last is a link to its own path prefix…
	await expect(trail.locator('a[href="/lineage"]')).toBeVisible();
	await expect(trail.locator('a[href="/lineage/datasets"]')).toBeVisible();
	// …and the leaf is the current page: text (not a link) and percent-decoded for reading.
	await expect(trail.locator('[aria-current="page"]')).toHaveText('silver$features');
	await expect(trail.locator('a[href*="silver"]')).toHaveCount(0);
});
