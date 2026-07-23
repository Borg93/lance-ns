import { test, expect, type Route } from '@playwright/test';

// Hermetic /namespaces coverage (#64 + the #85 drop lifecycle): the page derives namespaces from the
// catalog table list (there is no root-list endpoint), grouped by the `<namespace>$<table>` prefix.
// Mock the /capi calls it makes — the list, and the POST /v1/namespace/{id}/drop write (a successful
// drop mutates the mocked registry so the next poll returns the post-drop world).

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

let lastCapiPath = '';
let tables: string[] = [];
let dropPost: { path: string; body: unknown } | null = null;

test.beforeEach(async ({ page }) => {
	lastCapiPath = '';
	tables = ['bronze$events', 'gold$catalog', 'gold$metrics'];
	dropPost = null;
	await page.route('**/capi/**', (route) => {
		lastCapiPath = new URL(route.request().url()).pathname;
		const path = lastCapiPath.replace(/^.*\/capi/, '');
		if (path === '/v1/table') {
			return json(route, { tables });
		}
		const drop = /^\/v1\/namespace\/([^/]+)\/drop$/.exec(path);
		if (drop) {
			const ns = decodeURIComponent(drop[1]);
			dropPost = { path, body: route.request().postDataJSON() as unknown };
			tables = tables.filter((t) => t !== ns && !t.startsWith(`${ns}$`));
			return json(route, {});
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

test('the New-namespace affordance points at the governed warehouse-bind flow', async ({
	page,
}) => {
	// Deliberate scope: no bare create surface here — creation goes through POST
	// /v1/warehouses/{id}/namespaces on the warehouses page (bucket-per-warehouse tenancy).
	await page.goto('/data/namespaces');
	await expect(page.getByRole('link', { name: 'New namespace' })).toHaveAttribute(
		'href',
		'/data/warehouses',
	);
});

test('drop confirms via the AlertDialog, posts the cascade behavior, and the row disappears', async ({
	page,
}) => {
	await page.goto('/data/namespaces');
	await expect(page.locator('section.ns', { hasText: 'bronze' })).toBeVisible();
	await page.getByRole('button', { name: 'Drop namespace bronze' }).click();
	// The confirm is the portalled @rask/ui AlertDialog — drive it by role, not the trigger row.
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('Drop namespace bronze');
	await dialog.getByRole('checkbox').check(); // Cascade — bronze holds a table, Restrict would refuse
	await dialog.getByRole('button', { name: 'Drop', exact: true }).click();
	expect(dropPost).toEqual({ path: '/v1/namespace/bronze/drop', body: { behavior: 'Cascade' } });
	// The success re-load renders the post-drop registry: bronze gone, gold intact.
	await expect(page.locator('section.ns', { hasText: 'bronze' })).toHaveCount(0);
	await expect(page.locator('section.ns', { hasText: 'gold' })).toBeVisible();
	await expect(page.locator('.banner.ok')).toContainText('namespace bronze dropped (cascade)');
});

test('cancelling the confirm never posts the drop', async ({ page }) => {
	await page.goto('/data/namespaces');
	await page.getByRole('button', { name: 'Drop namespace gold' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click();
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
	expect(dropPost).toBeNull();
	await expect(page.locator('section.ns', { hasText: 'gold' })).toBeVisible();
});

test('a 403 drop surfaces the forbidden state and keeps the namespace listed', async ({ page }) => {
	// A later page.route wins over the beforeEach glob — deny the drop like the catalog's FGA gate
	// (owner-tier can_delete) does for a non-owner.
	await page.route('**/capi/v1/namespace/**', (route) => json(route, { detail: 'forbidden' }, 403));
	await page.goto('/data/namespaces');
	await page.getByRole('button', { name: 'Drop namespace gold' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: 'Drop', exact: true }).click();
	await expect(page.locator('.banner.fail')).toContainText(
		'Denied: dropping gold needs the owner rung (can_delete).',
	);
	await expect(page.locator('section.ns', { hasText: 'gold' })).toBeVisible();
});

test('the shared sidebar marks the Namespaces leaf active', async ({ page }) => {
	await page.goto('/data/namespaces');
	// The AppShell sidebar (shared @rask/ui) reflects the current route via data-active.
	await expect(
		page.locator('[data-active="true"]').filter({ hasText: 'Namespaces' }),
	).toBeVisible();
});
