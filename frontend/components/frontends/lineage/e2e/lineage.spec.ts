import { test, expect, type Route } from '@playwright/test';

// The medallion DAG the mocked lineage API returns. GraphEdge semantics: `source` is derived_from
// `target` (output → input), matching services/lineage/schemas.py.
const NODES = [
	{ id: 'raw_events', namespace: 'raw', source_uri: 's3://lakehouse/raw_events', tags: [] },
	{
		id: 'bronze$events',
		namespace: 'bronze',
		source_uri: 's3://lakehouse/bronze',
		tags: ['layer=bronze'],
	},
	{
		id: 'silver$features',
		namespace: 'silver',
		source_uri: 's3://lakehouse/silver',
		tags: ['layer=silver'],
	},
	{
		id: 'gold$catalog',
		namespace: 'gold',
		source_uri: 's3://lakehouse/gold',
		tags: ['layer=gold'],
	},
];
const EDGES = [
	{ source: 'bronze$events', target: 'raw_events', kind: 'derived_from' },
	{ source: 'silver$features', target: 'bronze$events', kind: 'derived_from' },
	{ source: 'gold$catalog', target: 'silver$features', kind: 'derived_from' },
];

const json = (route: Route, body: unknown) =>
	route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

// Stub every lineage-API call the UI makes through the SvelteKit proxy — no live backend needed.
// Mutable per-test governance state (#49) so the write tests can assert the round-trip.
let governance: { tags: string[]; description: string | null };

test.beforeEach(async ({ page }) => {
	governance = { tags: ['layer=silver'], description: null };
	await page.route('**/api/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/api/, '');
		const gov = path.match(/^\/datasets\/([^/]+)\/governance$/);
		if (gov)
			return json(route, {
				name: decodeURIComponent(gov[1]),
				tags: governance.tags,
				description: governance.description,
				tags_updated_by: 'alice',
				tags_updated_at: '2026-07-16T00:00:00+00:00',
			});
		const tagWrite = path.match(/^\/datasets\/([^/]+)\/tags\/([^/]+)$/);
		if (tagWrite) {
			const tag = decodeURIComponent(tagWrite[2]);
			if (req.method() === 'PUT' && !governance.tags.includes(tag)) governance.tags.push(tag);
			if (req.method() === 'DELETE') governance.tags = governance.tags.filter((t) => t !== tag);
			return json(route, {
				name: decodeURIComponent(tagWrite[1]),
				tags: governance.tags,
				description: governance.description,
				tags_updated_by: 'alice',
				tags_updated_at: '2026-07-16T00:00:00+00:00',
			});
		}
		const desc = path.match(/^\/datasets\/([^/]+)\/description$/);
		if (desc && req.method() === 'PUT') {
			governance.description = (req.postDataJSON() as { description: string }).description;
			return json(route, {
				name: decodeURIComponent(desc[1]),
				tags: governance.tags,
				description: governance.description,
				description_updated_by: 'alice',
				description_updated_at: '2026-07-16T00:00:00+00:00',
			});
		}
		const creator = path.match(/^\/datasets\/([^/]+)\/creator$/);
		if (creator)
			return json(route, { dataset: decodeURIComponent(creator[1]), creator: 'user:founder' });
		const schema = path.match(/^\/datasets\/([^/]+)\/schema$/);
		if (schema) {
			const v = new URL(req.url()).searchParams.get('version');
			// Time-travel: v1 had only `id`; the latest (v2) added `embedding` — distinct per version.
			const fields =
				v === '1'
					? [{ name: 'id', type: 'int64' }]
					: [
							{ name: 'id', type: 'int64' },
							{ name: 'embedding', type: 'list<float>' },
						];
			return json(route, {
				dataset: decodeURIComponent(schema[1]),
				version: v ? Number(v) : 2,
				fields,
			});
		}
		const runInputs = path.match(/^\/runs\/([^/]+)\/inputs$/);
		if (runInputs)
			return json(route, {
				run_id: decodeURIComponent(runInputs[1]),
				inputs: [{ name: 'bronze$events', version: '1' }],
			});
		const readers = path.match(/^\/datasets\/([^/]+)\/readers$/);
		if (readers)
			return json(route, {
				dataset: decodeURIComponent(readers[1]),
				readers: [{ reader: 'user:alice', reads: 3, last_read: '2026-07-16T09:00:00+00:00' }],
			});
		const m = path.match(/^\/datasets\/([^/]+)\/(producers|graph|columns)/);
		if (m) {
			const id = decodeURIComponent(m[1]);
			if (m[2] === 'producers')
				return json(route, {
					dataset: id,
					producers: [
						{
							run_id: `run-${id}`,
							author: 'alice',
							event_type: 'COMPLETE',
							dataset_version: '1',
							event_time: '2026-07-01T00:00:00Z',
						},
					],
				});
			if (m[2] === 'graph') return json(route, { root: id, nodes: NODES, edges: EDGES });
			return json(route, { root: id, columns: [], edges: [] }); // columns
		}
		if (path === '/datasets')
			return json(route, {
				datasets: NODES.map((n) => ({ name: n.id, namespace: n.namespace, tags: n.tags })),
				total: NODES.length,
			});
		if (path === '/events') return json(route, { events: [] });
		if (path === '/runs')
			return json(route, {
				runs: [
					{
						run_id: 'r-1',
						job: 'ray-jobs/embed_features',
						state: 'RUNNING',
						progress_done: 1,
						progress_total: 3,
						author: 'alice',
						outputs: ['silver$features'],
						updated_at: '2026-07-01T00:00:00Z',
						events: 2,
					},
					{
						run_id: 'r-2',
						job: 'ray-jobs/promote_gold',
						state: 'FAIL',
						author: 'bob',
						error_message: 'quality gate: row_count below floor',
						updated_at: '2026-07-01T00:01:00Z',
						events: 3,
					},
				],
			});
		if (path === '/jobs')
			return json(route, {
				jobs: [
					{ namespace: 'lance-medallion', name: 'embed_features', outputs: ['silver$features'] },
				],
				total: 1,
			});
		if (path === '/namespaces')
			return json(route, { namespaces: ['bronze', 'gold', 'raw', 'silver'] });
		if (path.startsWith('/search'))
			return json(route, {
				query: 'embed',
				results: [
					{ name: 'silver$features', namespace: 'silver', tags: [], matches: ['column:embedding'] },
				],
				total: 1,
			});
		if (path === '/demo/datasets') return json(route, { datasets: [] });
		return json(route, {});
	});
});

test('renders the medallion DAG at /lineage', async ({ page }) => {
	await page.goto('/lineage');
	// SvelteFlow wraps each custom node in .svelte-flow__node — the 4 medallion datasets.
	const nodes = page.locator('.svelte-flow__node');
	await expect(nodes).toHaveCount(4, { timeout: 15_000 });
	// Scope to graph nodes — the browse-panel list also renders these names (the node's URI div also
	// contains the name, so filter by the node, not exact text).
	await expect(nodes.filter({ hasText: 'raw_events' })).toBeVisible();
	await expect(nodes.filter({ hasText: 'gold$catalog' })).toBeVisible();
});

test('clicking a dataset node shows its upstream + downstream in the detail panel', async ({
	page,
}) => {
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

test('the Read by panel lazily loads the read-audit log for the selected dataset (#41)', async ({
	page,
}) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });

	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Details' }).click();
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();

	// Collapsed + lazy: the reader is not fetched/shown until the section is opened.
	await expect(page.getByText('user:alice')).toBeHidden();
	await page.getByRole('button', { name: 'Read by' }).click();
	// The mocked read-audit log renders: the principal + its aggregated read count.
	await expect(page.getByText('user:alice')).toBeVisible();
	await expect(page.getByText('3 reads')).toBeVisible();
});

test('a producing run reveals its pinned input versions on demand — reproducibility (#115)', async ({
	page,
}) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });

	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Details' }).click();
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();

	// Lazy: the pin is not shown until the run's "reads" toggle is opened (kept off the hot board).
	await expect(page.getByText('bronze$events@1')).toBeHidden();
	await page.getByRole('button', { name: 'reads' }).click();
	// The pinned READ version the run consumed — "which feature version produced this output".
	await expect(page.getByText('bronze$events@1')).toBeVisible();
});

test('the detail panel shows the creator and steps schema through Lance versions (#24)', async ({
	page,
}) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });

	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Details' }).click();
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();

	// Creator: who ORIGINATED the table (verified catalog principal), loaded eagerly.
	await expect(page.getByText('user:founder')).toBeVisible();

	// Schema time-travel: latest (v2) carries the embedding column; stepping back to v1 drops it.
	await page.getByRole('button', { name: 'Schema', exact: false }).click();
	await expect(page.locator('.fname', { hasText: 'embedding' })).toBeVisible();
	await page.getByRole('button', { name: 'v1', exact: true }).click();
	await expect(page.locator('.fname', { hasText: 'embedding' })).toHaveCount(0);
	await expect(page.locator('.fname')).toHaveText('id');
});

test('browse landing lists datasets from /datasets, filters, and focuses on click', async ({
	page,
}) => {
	await page.goto('/lineage');
	// Browse is the default aside tab — the governed /datasets catalog renders as a filterable list, so a
	// visitor can start with no dataset name in hand (GOAL 4 A3).
	const rows = page.locator('.browse-row');
	await expect(rows).toHaveCount(4, { timeout: 15_000 });
	await expect(page.locator('.browse-name', { hasText: 'raw_events' })).toBeVisible();

	// Filtering narrows the list to matches (by name / namespace / tag).
	await page.getByLabel('Filter datasets').fill('silver');
	await expect(rows).toHaveCount(1);
	await expect(page.locator('.browse-name')).toHaveText('silver$features');

	// Clicking a dataset focuses it — the row is marked selected and Details reflects it.
	await rows.first().click();
	await expect(page.locator('.browse-row.on')).toHaveCount(1);
	await page.getByRole('tab', { name: 'Details' }).click();
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
});

test('governed search finds by column and focuses the hit; jobs tab lists compute identities', async ({
	page,
}) => {
	// ASSERTS (Batch 12): the SearchBar (packages/ui) drives the governed /search endpoint — a
	// column-tier hit renders its WHY-chip (column:embedding) and selecting it focuses the dataset;
	// the new Jobs tab lists the governed compute identities with clickable outputs.
	await page.goto('/lineage');
	await page.getByLabel('search').fill('embed');
	const hit = page.getByRole('listbox').getByRole('button');
	await expect(hit).toContainText('silver$features');
	await expect(hit).toContainText('column:embedding'); // the match-reason chip
	await hit.click();
	await page.getByRole('tab', { name: 'Details' }).click();
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();

	await page.getByRole('tab', { name: 'Jobs (1)' }).click();
	// Scope to the jobs list's own class — the status board's run row ALSO contains this job name
	// and bits-ui keeps inactive tab content in the DOM (the Batch 12 collision lesson).
	await expect(page.locator('.job-name', { hasText: 'embed_features' })).toBeVisible();
});

test('columns view: clicking a field opens its provenance/impact panel with the masking cue', async ({
	page,
}) => {
	// ASSERTS (#24 field lineage): the two per-field endpoints (columns/{field}/upstream|downstream) now
	// have a frontend caller. Clicking a ColumnNode opens the side panel listing that field's direct
	// provenance + impact, each with its transformation kind, and the same red PII cue on a masking hop.
	// Column subgraph for silver$features: a masking derivation into pii_hash + a plain hop out of it.
	const COLGRAPH = {
		root: 'silver$features',
		columns: [
			{ dataset: 'bronze$events', field: 'pii_email', type: 'string' },
			{ dataset: 'silver$features', field: 'pii_hash', type: 'string' },
			{ dataset: 'gold$catalog', field: 'exposed', type: 'bool' },
		],
		edges: [
			{
				source_dataset: 'bronze$events',
				source_field: 'pii_email',
				target_dataset: 'silver$features',
				target_field: 'pii_hash',
				transformation_type: 'MASKED',
				transformation_subtype: 'sha256',
				masking: true,
			},
			{
				source_dataset: 'silver$features',
				source_field: 'pii_hash',
				target_dataset: 'gold$catalog',
				target_field: 'exposed',
				transformation_type: 'IDENTITY',
				transformation_subtype: '',
				masking: false,
			},
		],
	};
	// Registered after beforeEach → these more-specific routes win for their URLs (columns graph vs the
	// two per-field neighbor endpoints), leaving every other /api call to the shared mock.
	await page.route('**/datasets/*/columns', (route) => json(route, COLGRAPH));
	await page.route('**/columns/*/upstream', (route) =>
		json(route, {
			dataset: 'silver$features',
			field: 'pii_hash',
			related: [{ dataset: 'bronze$events', field: 'pii_email', type: 'string' }],
		}),
	);
	await page.route('**/columns/*/downstream', (route) =>
		json(route, {
			dataset: 'silver$features',
			field: 'pii_hash',
			related: [{ dataset: 'gold$catalog', field: 'exposed', type: 'bool' }],
		}),
	);

	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	// Focus silver$features, then switch to the Columns plane — the field-to-field subgraph renders.
	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Columns' }).click();
	const piiNode = page.locator('.svelte-flow__node').filter({ hasText: 'pii_hash' });
	await expect(piiNode).toBeVisible({ timeout: 15_000 });

	// Click the column node → the field panel opens for that field.
	await piiNode.click();
	const panel = page.locator('.field-panel');
	await expect(panel).toBeVisible();
	await expect(panel.locator('.fp-field')).toHaveText('pii_hash');
	// Provenance: derived from bronze pii_email via a MASKED sha256 hop → the row carries the red cue.
	await expect(panel.getByText('pii_email')).toBeVisible();
	await expect(panel.getByText('sha256')).toBeVisible();
	await expect(panel.locator('.fp-row.masked')).toHaveCount(1);
	// Impact: pii_hash feeds gold.exposed (a non-masking hop).
	await expect(panel.getByText('exposed')).toBeVisible();

	// Walking the chain: clicking an upstream column re-focuses the panel on it.
	await panel.getByText('pii_email').click();
	await expect(panel.locator('.fp-field')).toHaveText('pii_email');
});

test('status board renders live runs from the workspace lib (@rask/ui StatusBoard)', async ({
	page,
}) => {
	// ASSERTS (Batch 14): the EXTRACTED StatusBoard renders real rows under the host app — the
	// Batch 12 lesson was that a workspace-lib component can compile clean yet break only at
	// render/interaction time, so the extraction is pinned by rendered output, not just svelte-check.
	// One RUNNING row (progress label from progress_done/total) + one FAIL row (error strip).
	await page.goto('/lineage');
	await page.getByRole('tab', { name: 'Status (2)' }).click();
	await expect(page.getByText('embed_features', { exact: false }).first()).toBeVisible();
	await expect(page.getByText('RUNNING 1/3')).toBeVisible();
	await expect(page.getByText('FAIL', { exact: true })).toBeVisible();
	await expect(page.getByText('quality gate: row_count below floor')).toBeVisible();
	await expect(page.getByText('→ silver$features')).toBeVisible();
});

test('governance: tag add/remove and description edit round-trip in the details panel', async ({
	page,
}) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await page.getByRole('tab', { name: 'Details' }).click();
	const panel = page.locator('.governance');
	await expect(panel.locator('.tag', { hasText: 'layer=silver' })).toBeVisible();

	// Add a governance tag — the chip appears from the write response.
	await panel.getByLabel('Add governance tag').fill('pii');
	await panel.locator('.tag-add button').click();
	await expect(panel.locator('.tag', { hasText: 'pii' })).toBeVisible();
	await expect(panel.locator('.attribution')).toContainText('alice');

	// Remove it again — the chip disappears.
	await panel.locator('.tag', { hasText: 'pii' }).locator('.tag-x').click();
	await expect(panel.locator('.tag', { hasText: 'pii' })).toHaveCount(0);

	// Description: placeholder → edit → saved text renders.
	await panel.locator('.desc').click();
	await panel.locator('textarea').fill('Daily silver feature table');
	await panel.getByRole('button', { name: 'Save' }).click();
	await expect(panel.locator('.desc')).toContainText('Daily silver feature table');
});
