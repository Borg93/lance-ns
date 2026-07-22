import { test, expect, type Route } from '@playwright/test';

// Hermetic /namespaces coverage (#64): the page derives namespaces from the catalog table list (there is
// no root-list endpoint), grouped by the `<namespace>$<table>` prefix. Mock the one /capi call it makes.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

let lastCapiPath = '';

test.beforeEach(async ({ page }) => {
	lastCapiPath = '';
	await page.route('**/capi/**', (route) => {
		lastCapiPath = new URL(route.request().url()).pathname;
		const path = lastCapiPath.replace(/^.*\/capi/, '');
		if (path === '/v1/table') {
			return json(route, { tables: ['bronze$events', 'gold$catalog', 'gold$metrics'] });
		}
		return json(route, { detail: 'unstubbed' }, 404);
	});
});

test('the client fetches the BFF under the zone base path, not a bare /capi', async ({ page }) => {
	// Regression lock for the base-path bug: the zone is served under /data, so its BFF proxy lives at
	// /data/capi/* — a bare /capi never reaches this zone through the Ingress (proven: bare → 404). The
	// mocked glob (**/capi/**) matches both, so THIS asserts the real request carries the base.
	await page.goto('/data/namespaces');
	// Poll — the fetch fires from an $effect after mount, so wait for the intercept rather than racing it.
	await expect.poll(() => lastCapiPath).toBe('/data/capi/v1/table');
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
