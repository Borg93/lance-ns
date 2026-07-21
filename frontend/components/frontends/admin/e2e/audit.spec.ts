import { test, expect, type Route } from '@playwright/test';

// Hermetic /audit coverage (#77): the viewer reads the #41 compliance trail via the /api/audit BFF. Mock it;
// assert the events render, the outcome filter re-queries, and the nav exposes the route.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

const EVENTS = [
	{
		timestamp: '2026-07-20T10:00:00Z',
		action: 'can_drop',
		outcome: 'DENY',
		subject: 'user:bob',
		resource: 'table:db1$t',
	},
	{
		timestamp: '2026-07-20T09:00:00Z',
		action: 'can_read_data',
		outcome: 'ALLOW',
		subject: 'user:alice',
		resource: 'table:db1$t',
	},
];

let lastQuery = '';

test.beforeEach(async ({ page }) => {
	lastQuery = '';
	await page.route('**/api/audit**', (route) => {
		const url = new URL(route.request().url());
		lastQuery = url.search;
		const outcome = url.searchParams.get('outcome');
		const events = outcome ? EVENTS.filter((e) => e.outcome === outcome) : EVENTS;
		return json(route, { events });
	});
});

test('renders the audit trail rows', async ({ page }) => {
	await page.goto('/admin/audit');
	await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();
	const table = page.locator('table');
	await expect(table).toContainText('can_drop');
	await expect(table).toContainText('user:bob');
	await expect(table).toContainText('can_read_data');
});

test('the outcome filter re-queries the BFF', async ({ page }) => {
	await page.goto('/admin/audit');
	await expect(page.locator('table')).toContainText('can_read_data');
	// the outcome picker is the @lance/ui Select (bits-ui)
	await page.getByLabel('Outcome filter').click();
	await page.getByRole('option', { name: 'DENY', exact: true }).click();
	await expect.poll(() => lastQuery).toContain('outcome=DENY');
	await expect(page.locator('table')).not.toContainText('can_read_data'); // filtered out
	await expect(page.locator('table')).toContainText('can_drop');
});

test('the shared sidebar marks the Audit leaf active', async ({ page }) => {
	await page.goto('/admin/audit');
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Audit' })).toBeVisible();
});
