import { test } from '@playwright/test';

// Compile-warm the dev server before the parallel suite (see playwright.config.ts projects comment).
// No mocks here — failed /capi calls are irrelevant; goto resolving means Vite compiled the route.
test('warm the dev server routes', async ({ page }) => {
	test.setTimeout(180_000);
	for (const path of [
		'/data/tables',
		'/data/tables/db1%24t',
		'/data/namespaces',
		'/data/namespaces/gold',
		'/data/warehouses',
		'/data/warehouses/acme-wh',
		'/data/projects',
		'/data/projects/acme',
	]) {
		await page.goto(path).catch(() => {});
	}
});
