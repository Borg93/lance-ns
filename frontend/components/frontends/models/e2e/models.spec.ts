import { test, expect, type Route } from '@playwright/test';

// Hermetic /models coverage: every catalog call the page makes goes through the /capi BFF proxy,
// stubbed here — no live catalog needed (same pattern as lineage.spec.ts).

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

// Mutable so the promote test can flip the blessed pointer and assert the UI refresh.
let models: { model: string; latest_version: number | null; blessed_version: number | null }[];

test.beforeEach(async ({ page }) => {
	models = [
		{ model: 'demo', latest_version: 3, blessed_version: 2 },
		{ model: 'fraud', latest_version: 1, blessed_version: null },
	];
	await page.route('**/capi/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^\/capi/, '');
		const promote = path.match(/^\/v1\/model\/([^/]+)\/promote$/);
		if (promote && req.method() === 'POST') {
			const name = decodeURIComponent(promote[1]);
			const body = req.postDataJSON() as { version: number };
			const entry = models.find((m) => m.model === name);
			if (entry) entry.blessed_version = body.version;
			return json(route, { model: name, blessed_version: body.version, tag: 'blessed' });
		}
		const one = path.match(/^\/v1\/model\/([^/]+)$/);
		if (one) {
			const name = decodeURIComponent(one[1]);
			const entry = models.find((m) => m.model === name);
			return json(route, {
				model: name,
				latest_version: entry?.latest_version ?? 1,
				blessed_version: entry?.blessed_version ?? null,
				candidate_metrics: { rows_seen: 9, loss: 0.1234 },
				blessed_metrics: entry?.blessed_version ? { rows_seen: 4, loss: 0.5 } : null,
			});
		}
		if (path === '/v1/model') return json(route, { models });
		return json(route, { detail: 'unstubbed' }, 404);
	});
});

test('registry list renders candidate/blessed state per model', async ({ page }) => {
	await page.goto('/models');
	await expect(page.getByRole('heading', { name: 'Model registry' })).toBeVisible();
	const demoRow = page.locator('tr', { hasText: 'demo' }).first();
	await expect(demoRow).toContainText('v3');
	await expect(demoRow).toContainText('blessed behind');
	const fraudRow = page.locator('tr', { hasText: 'fraud' }).first();
	await expect(fraudRow).toContainText('candidate only');
});

test('clicking a model opens the candidate-vs-blessed metrics panel', async ({ page }) => {
	await page.goto('/models');
	await page.locator('td', { hasText: 'demo' }).first().click();
	await expect(page.locator('.metrics')).toBeVisible();
	await expect(page.locator('.metrics')).toContainText('rows_seen');
	await expect(page.locator('.metrics')).toContainText('0.1234'); // candidate loss
	await expect(page.locator('.metrics')).toContainText('0.5000'); // blessed loss
});

test('bless promotes the candidate and the row updates', async ({ page }) => {
	await page.goto('/models');
	const demoRow = page.locator('tr', { hasText: 'demo' }).first();
	await demoRow.getByRole('button', { name: 'bless v3' }).click();
	await expect(page.locator('.banner.ok')).toContainText('demo v3 is now blessed');
	await expect(demoRow).toContainText('blessed'); // state chip converges after the refetch
	await expect(demoRow.getByRole('button')).toHaveCount(0); // nothing left to bless
});

test('the shared sidebar marks Registry active and links to Lineage as a cross-zone hard nav', async ({
	page,
}) => {
	await page.goto('/models');
	// On the models zone root the Registry leaf is active (exact-match — not lit on sibling sub-routes).
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'Registry' })).toBeVisible();
	// Lineage is a DIFFERENT MFE zone: its sidebar link is a full-document reload (data-sveltekit-reload),
	// not a soft SPA nav, so leaving this app's route manifest re-bootstraps the lineage app.
	const lineage = page.getByRole('link', { name: 'Lineage' });
	await expect(lineage).toHaveAttribute('href', '/lineage');
	await expect(lineage).toHaveAttribute('data-sveltekit-reload', '');
});
