import { test, expect, type Route } from '@playwright/test';

// The medallion DAG the mocked lineage API returns. GraphEdge semantics: `source` is derived_from
// `target` (output → input), matching services/lineage/schemas.py.
const NODES = [
	{ id: 'raw_events', namespace: 'raw', source_uri: 's3://lakehouse/raw_events', tags: [] },
	{ id: 'bronze$events', namespace: 'bronze', source_uri: 's3://lakehouse/bronze', tags: ['layer=bronze'] },
	{ id: 'silver$features', namespace: 'silver', source_uri: 's3://lakehouse/silver', tags: ['layer=silver'] },
	{ id: 'gold$catalog', namespace: 'gold', source_uri: 's3://lakehouse/gold', tags: ['layer=gold'] }
];
const EDGES = [
	{ source: 'bronze$events', target: 'raw_events', kind: 'derived_from' },
	{ source: 'silver$features', target: 'bronze$events', kind: 'derived_from' },
	{ source: 'gold$catalog', target: 'silver$features', kind: 'derived_from' }
];

const json = (route: Route, body: unknown) =>
	route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

// Stub every lineage-API call the UI makes through the SvelteKit proxy — no live backend needed.
test.beforeEach(async ({ page }) => {
	await page.route('**/api/**', (route) => {
		const path = new URL(route.request().url()).pathname.replace(/^\/api/, '');
		const m = path.match(/^\/datasets\/([^/]+)\/(producers|graph|columns)/);
		if (m) {
			const id = decodeURIComponent(m[1]);
			if (m[2] === 'producers')
				return json(route, {
					dataset: id,
					producers: [
						{ run_id: `run-${id}`, author: 'alice', event_type: 'COMPLETE', dataset_version: '1', event_time: '2026-07-01T00:00:00Z' }
					]
				});
			if (m[2] === 'graph') return json(route, { root: id, nodes: NODES, edges: EDGES });
			return json(route, { root: id, columns: [], edges: [] }); // columns
		}
		if (path === '/events') return json(route, { events: [] });
		if (path === '/runs') return json(route, { runs: [] });
		if (path === '/demo/datasets') return json(route, { datasets: [] });
		return json(route, {});
	});
});

test('renders the medallion DAG at /lineage', async ({ page }) => {
	await page.goto('/lineage');
	// SvelteFlow wraps each custom node in .svelte-flow__node — the 4 medallion datasets.
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	// exact:true — the node's URI div (s3://lakehouse/raw_events) also contains "raw_events".
	await expect(page.getByText('raw_events', { exact: true })).toBeVisible();
	await expect(page.getByText('gold$catalog', { exact: true })).toBeVisible();
});

test('clicking a dataset node shows its upstream + downstream in the detail panel', async ({ page }) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });

	// Click the silver node — it has both an upstream (bronze) and a downstream (gold).
	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Details' }).click();

	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
	await expect(page.getByText('Upstream')).toBeVisible();
	await expect(page.getByRole('button', { name: 'bronze$events' })).toBeVisible();
	await expect(page.getByText('Downstream')).toBeVisible();
	await expect(page.getByRole('button', { name: 'gold$catalog' })).toBeVisible();

	// The upstream chip reselects that dataset — the panel follows.
	await page.getByRole('button', { name: 'bronze$events' }).click();
	await expect(page.getByRole('heading', { name: 'bronze$events' })).toBeVisible();
});
