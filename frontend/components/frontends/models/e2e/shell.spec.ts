import { test, expect, type Route } from '@playwright/test';

// The estate shell in the MODELS zone: the cross-zone TopNavbar fed by a mocked /v1/me (hermetic —
// the layout fetches it through this zone's /capi/v1/me pass-through), and the zone-scoped sidebar
// carrying ONLY this zone's own routes.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

test('an estate admin gets the full navbar entry set + the models sidebar leaves', async ({
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
	await page.goto('/models');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Models' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Admin' })).toBeVisible();
	// Access is NOT a top-level entry (4b2af0e: it folds into the admin zone's own sidebar).
	await expect(nav.getByRole('link', { name: 'Access' })).toHaveCount(0);
	// The sidebar renders ONLY this zone's own routes.
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Registry' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Pipeline' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Experiments' })).toBeVisible();
});

test('a signed-out / unresolved identity renders the base entries only (fail-closed)', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/models');
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Data' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0);
	await expect(nav.getByRole('link', { name: 'Access' })).toHaveCount(0);
});

test('the project switcher heads the navbar row — it no longer lives in the sidebar', async ({
	page,
}) => {
	await page.route('**/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.goto('/models');
	const switcher = page.getByRole('button', { name: 'Switch project' });
	await expect(switcher).toBeVisible();
	// The sidebar header is gone entirely: the sidebar is in-zone routes only.
	await expect(page.locator('[data-sidebar="header"]')).toHaveCount(0);
	// It sits on the navbar row, left of the zone links.
	const switcherBox = (await switcher.boundingBox())!;
	const zonesBox = (await page.getByRole('navigation', { name: 'Zones' }).boundingBox())!;
	expect(switcherBox.x).toBeLessThan(zonesBox.x);
	expect(switcherBox.y).toBeLessThan(zonesBox.y + zonesBox.height);
});
