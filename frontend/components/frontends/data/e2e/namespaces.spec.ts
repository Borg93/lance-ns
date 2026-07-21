import { test, expect, type Route } from '@playwright/test';

// Hermetic /namespaces coverage (#64): the page derives namespaces from the catalog table list (there is
// no root-list endpoint), grouped by the `<namespace>$<table>` prefix. Mock the one /capi call it makes.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

test.beforeEach(async ({ page }) => {
	await page.route('**/capi/**', (route) => {
		const path = new URL(route.request().url()).pathname.replace(/^\/capi/, '');
		if (path === '/v1/table') {
			return json(route, { tables: ['bronze$events', 'gold$catalog', 'gold$metrics'] });
		}
		return json(route, { detail: 'unstubbed' }, 404);
	});
});

test('groups the catalog tables by namespace with per-namespace table counts', async ({ page }) => {
	await page.goto('/data/namespaces');
	await expect(page.getByRole('heading', { name: 'Namespaces' })).toBeVisible();
	const bronze = page.locator('section.ns', { hasText: 'bronze' });
	await expect(bronze).toContainText('1 table');
	const gold = page.locator('section.ns', { hasText: 'gold' });
	await expect(gold).toContainText('2 tables');
	// tables link into the detail view
	await expect(gold.locator('a', { hasText: 'gold$catalog' })).toHaveAttribute(
		'href',
		'/data/tables/gold%24catalog',
	);
});

test('the shared sidebar marks the Namespaces leaf active', async ({ page }) => {
	await page.goto('/data/namespaces');
	// The AppShell sidebar (shared @rask/ui) reflects the current route via data-active.
	await expect(
		page.locator('[data-active="true"]').filter({ hasText: 'Namespaces' }),
	).toBeVisible();
});
