import { test, expect, type Route } from '@playwright/test';

// Hermetic e2e for the Marquez-parity IA: first-class Datasets / Jobs / Runs / Columns views +
// per-dataset and per-job detail pages, with the DAG explorer at the zone root. The medallion DAG
// the mocked lineage API returns — GraphEdge semantics: `source` is derived_from `target`
// (output → input), matching services/lineage/schemas.py.
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
// run.job is `namespace/name` (repository.py); the jobs list carries the same identity split.
const RUNS = [
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
		outputs: [],
		updated_at: '2026-07-01T00:01:00Z',
		events: 3,
	},
];
const EVENTS = [
	{
		seq: 2,
		event_type: 'COMPLETE',
		event_time: '2026-07-01T00:00:30Z',
		job: 'ray-jobs/embed_features',
		author: 'alice',
		inputs: ['bronze$events'],
		outputs: ['silver$features'],
		event: {
			run: { runId: 'r-1', facets: { processing_engine: { name: 'ray' } } },
			job: {
				namespace: 'ray-jobs',
				name: 'embed_features',
				facets: { jobType: { jobType: 'BATCH' } },
			},
		},
	},
	{
		seq: 1,
		event_type: 'START',
		event_time: '2026-07-01T00:00:00Z',
		job: 'ray-jobs/embed_features',
		author: 'alice',
		inputs: ['bronze$events'],
		outputs: ['silver$features'],
		event: { run: { runId: 'r-1' } },
	},
];

const json = (route: Route, body: unknown) =>
	route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

// Stub every lineage-API call the UI makes through the SvelteKit proxy — no live backend needed.
// Mutable per-test governance state (#49) so the write tests can assert the round-trip.
let governance: { tags: string[]; description: string | null };

test.beforeEach(async ({ page }) => {
	governance = { tags: ['layer=silver'], description: null };
	// Scope to the zone's BFF base (/lineage/api/…) — a bare **/api/** also swallows Vite's
	// /@fs module requests for the @rask/api workspace package (its path contains /api/), which
	// kills hydration with JSON-as-module (found 2026-07-24 when the layout began importing it).
	await page.route('**/lineage/api/**', (route) => {
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
		const neighbors = path.match(/^\/datasets\/([^/]+)\/(upstream|downstream)$/);
		if (neighbors) {
			const id = decodeURIComponent(neighbors[1]);
			// GraphEdge semantics: source derived_from target ⇒ upstream(id) = targets of id's edges.
			const related =
				neighbors[2] === 'upstream'
					? EDGES.filter((e) => e.source === id).map((e) => ({ name: e.target }))
					: EDGES.filter((e) => e.target === id).map((e) => ({ name: e.source }));
			return json(route, { dataset: id, related });
		}
		// The bulk estate read the DAG explorer polls (one request; per-node version/failed rollups).
		if (path === '/graph' || path.startsWith('/graph?'))
			return json(route, {
				nodes: NODES.map((n) => ({
					...n,
					versions: n.id === 'silver$features' ? ['2', '3'] : [],
					failed: false,
				})),
				edges: EDGES,
				total: NODES.length,
				capped: false,
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
		if (path === '/events') return json(route, { events: EVENTS });
		if (path === '/runs') return json(route, { runs: RUNS });
		if (path === '/jobs')
			return json(route, {
				jobs: [{ namespace: 'ray-jobs', name: 'embed_features', outputs: ['silver$features'] }],
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
		return json(route, {});
	});
});

// ---- Graph (the zone root stays a view — fixed) ----

test('the graph renders the medallion DAG with an honest LIVE header and no demo copy', async ({
	page,
}) => {
	await page.goto('/lineage');
	// SvelteFlow wraps each custom node in .svelte-flow__node — the 4 medallion datasets.
	const nodes = page.locator('.svelte-flow__node');
	await expect(nodes).toHaveCount(4, { timeout: 15_000 });
	await expect(nodes.filter({ hasText: 'raw_events' })).toBeVisible();
	await expect(nodes.filter({ hasText: 'gold$catalog' })).toBeVisible();
	// The status word says LIVE (not the old WAITING-with-data contradiction) …
	await expect(page.locator('.state-word')).toHaveText('live');
	// … the developer demo copy is gone …
	await expect(page.getByText('medallion_demo')).toHaveCount(0);
	// … and the layout-build perf readout renders a measured number.
	await expect(page.locator('header .perf')).toContainText('ms');
});

test('graph nodes lay out by computed depth — no two medallion nodes overlap', async ({ page }) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	// The linear DAG raw → bronze → silver → gold must occupy 4 DISTINCT x columns (the old
	// hardcoded-layer layout piled unknown datasets onto one x where labels overlapped). One root
	// ⇒ a 1-wide root grid, so the depth columns are unshifted.
	const xs = new Set<number>();
	for (const id of ['raw_events', 'bronze$events', 'silver$features', 'gold$catalog']) {
		const node = page.locator('.svelte-flow__node').filter({ hasText: id });
		const box = await node.boundingBox();
		xs.add(Math.round(box?.x ?? 0));
	}
	expect(xs.size).toBe(4);
});

test('a small estate is framed at 1:1 — fitView never blows the cards up', async ({ page }) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	await page.waitForTimeout(700); // let the fitView tween settle
	// The medallion card is 200px wide by design; with fitView maxZoom 1 the rendered card can be
	// SMALLER (zoomed out to frame a big graph) but never larger, so a 4-node estate no longer
	// renders as giant blocks filling the canvas.
	const box = await page.locator('.svelte-flow__node').first().boundingBox();
	expect(box?.width ?? 0).toBeGreaterThan(0);
	expect(box?.width ?? 0).toBeLessThanOrEqual(201);
});

test('depth-0 roots pack into a wrapped grid, not one tall column', async ({ page }) => {
	// Nine un-derived datasets: the old layout stacked all nine at one x (a 1000px tower that
	// forced fitView to zoom right out). They must now wrap into ceil(sqrt(9)) = 3 columns × 3 rows.
	const ROOTS = Array.from({ length: 9 }, (_, i) => ({
		id: `root_${i}`,
		namespace: 'roots',
		source_uri: `s3://lakehouse/root_${i}`,
		tags: [],
	}));
	await page.route(
		(url) => url.pathname.endsWith('/lineage/api/graph'),
		(route) => json(route, { nodes: ROOTS, edges: [], total: 9, capped: false }),
	);
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(9, { timeout: 15_000 });
	await page.waitForTimeout(700);

	const xs = new Set<number>();
	const ys = new Set<number>();
	for (let i = 0; i < 9; i += 1) {
		const box = await page
			.locator('.svelte-flow__node')
			.filter({ hasText: `root_${i}` })
			.boundingBox();
		xs.add(Math.round(box?.x ?? 0));
		ys.add(Math.round(box?.y ?? 0));
	}
	expect(xs.size).toBe(3);
	expect(ys.size).toBe(3);
});

test('clicking a graph node opens the dataset detail page', async ({ page }) => {
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(4, { timeout: 15_000 });
	await page.locator('.svelte-flow__node').filter({ hasText: 'silver$features' }).click();
	await expect(page).toHaveURL(/\/lineage\/datasets\/silver%24features$/);
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
});

// ---- Datasets (list + detail) ----

test('datasets view lists the governed catalog, filters, and row-links to detail', async ({
	page,
}) => {
	await page.goto('/lineage/datasets');
	const rows = page.locator('tbody tr');
	await expect(rows).toHaveCount(4, { timeout: 15_000 });
	await expect(page.getByRole('link', { name: 'raw_events' })).toBeVisible();

	// The text filter narrows the DataTable (name / namespace / tags all searchable).
	await page.getByPlaceholder('Filter datasets…').fill('silver');
	await expect(rows).toHaveCount(1);

	// Row-click → the per-dataset detail page.
	await page.getByRole('link', { name: 'silver$features' }).click();
	await expect(page).toHaveURL(/\/lineage\/datasets\/silver%24features$/);
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
});

test('governed search finds by column (why-chip) and opens the hit detail page', async ({
	page,
}) => {
	await page.goto('/lineage/datasets');
	await page.getByLabel('search').fill('embed');
	const hit = page.getByRole('listbox').getByRole('button');
	await expect(hit).toContainText('silver$features');
	await expect(hit).toContainText('column:embedding'); // the match-reason chip
	await hit.click();
	await expect(page).toHaveURL(/\/lineage\/datasets\/silver%24features$/);
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
});

test('dataset detail: creator, schema time-travel, upstream/downstream, runs with pins', async ({
	page,
}) => {
	await page.goto('/lineage/datasets/silver%24features');
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();

	// Creator: who ORIGINATED the table (verified catalog principal), loaded eagerly.
	await expect(page.getByText('user:founder')).toBeVisible({ timeout: 15_000 });

	// Schema time-travel: latest (v2) carries the embedding column; stepping back to v1 drops it.
	await page.getByRole('button', { name: 'Schema', exact: false }).click();
	await expect(page.locator('.fname', { hasText: 'embedding' })).toBeVisible();
	await page.getByRole('button', { name: 'v1', exact: true }).click();
	await expect(page.locator('.fname', { hasText: 'embedding' })).toHaveCount(0);
	await expect(page.locator('.fname')).toHaveText('id');

	// Upstream / downstream from the backend's own neighbor endpoints, as sibling-detail links.
	await expect(page.getByText('Upstream')).toBeVisible();
	await expect(page.getByRole('link', { name: 'bronze$events' })).toBeVisible();
	await expect(page.getByText('Downstream')).toBeVisible();
	await expect(page.getByRole('link', { name: 'gold$catalog' })).toBeVisible();

	// A producing run reveals its pinned input versions on demand — reproducibility (#115).
	await expect(page.getByText('bronze$events@1')).toBeHidden();
	await page.getByRole('button', { name: 'reads' }).click();
	await expect(page.getByText('bronze$events@1')).toBeVisible();

	// The upstream link navigates to that dataset's own detail page.
	await page.getByRole('link', { name: 'bronze$events' }).click();
	await expect(page).toHaveURL(/\/lineage\/datasets\/bronze%24events$/);
	await expect(page.getByRole('heading', { name: 'bronze$events' })).toBeVisible();
});

test('the Read by panel lazily loads the read-audit log for the dataset (#41)', async ({
	page,
}) => {
	await page.goto('/lineage/datasets/silver%24features');
	await expect(page.getByRole('heading', { name: 'silver$features' })).toBeVisible();
	// Wait for a client-fetched fact first — it proves hydration finished, so the toggle click
	// below lands on a live handler (an SSR-only button swallows it).
	await expect(page.getByText('user:founder')).toBeVisible({ timeout: 15_000 });

	// Collapsed + lazy: the reader is not fetched/shown until the section is opened.
	await expect(page.getByText('user:alice')).toBeHidden();
	await page.getByRole('button', { name: 'Read by' }).click();
	// The mocked read-audit log renders: the principal + its aggregated read count.
	await expect(page.getByText('user:alice')).toBeVisible();
	await expect(page.getByText('3 reads')).toBeVisible();
});

test('governance: tag add/remove and description edit round-trip on the detail page', async ({
	page,
}) => {
	await page.goto('/lineage/datasets/silver%24features');
	const panel = page.locator('.governance');
	await expect(panel.locator('.tag', { hasText: 'layer=silver' })).toBeVisible({ timeout: 15_000 });

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

// ---- Jobs (list + detail) ----

test('jobs view lists compute identities and row-links to the per-job detail page', async ({
	page,
}) => {
	await page.goto('/lineage/jobs');
	const rows = page.locator('tbody tr');
	await expect(rows).toHaveCount(1, { timeout: 15_000 });
	await expect(page.getByRole('link', { name: 'embed_features' })).toBeVisible();

	await page.getByRole('link', { name: 'embed_features' }).click();
	await expect(page).toHaveURL(/\/lineage\/jobs\/ray-jobs\/embed_features$/);
	await expect(page.getByRole('heading', { name: 'ray-jobs/embed_features' })).toBeVisible();
});

test('job detail: latest runs, read/write datasets, and the latest event facets', async ({
	page,
}) => {
	await page.goto('/lineage/jobs/ray-jobs/embed_features');
	await expect(page.getByRole('heading', { name: 'ray-jobs/embed_features' })).toBeVisible();

	// Latest runs: only THIS job's runs from the board (r-1), state + progress folded.
	await expect(page.getByText('RUNNING 1/3')).toBeVisible({ timeout: 15_000 });
	await expect(page.locator('.runid', { hasText: 'r-1' })).toBeVisible();
	await expect(page.locator('.runid', { hasText: 'r-2' })).toHaveCount(0); // the other job's run is not shown

	// Reads / writes folded from the job's events, linking to dataset detail pages.
	await expect(page.getByText('Reads', { exact: true })).toBeVisible();
	await expect(page.getByRole('link', { name: 'bronze$events' }).first()).toBeVisible();
	await expect(page.getByText('Writes', { exact: true })).toBeVisible();
	await expect(page.getByRole('link', { name: 'silver$features' }).first()).toBeVisible();

	// Facets: the latest event's run/job facets render spec-true.
	await expect(page.locator('.json').first()).toContainText('processing_engine');
	await expect(page.locator('.json').first()).toContainText('jobType');
});

// ---- Runs ----

test('runs view: DataTable board with state badges, and a drill-in with error + pins', async ({
	page,
}) => {
	await page.goto('/lineage/runs');
	const rows = page.locator('tbody tr');
	await expect(rows).toHaveCount(2, { timeout: 15_000 });
	await expect(page.getByText('RUNNING 1/3')).toBeVisible();
	await expect(page.getByText('FAIL', { exact: true })).toBeVisible();

	// The failed run's drill-in: error strip + outputs; the pins load lazily via "reads".
	await page.getByRole('button', { name: 'r-2' }).click();
	const drill = page.locator('.drill');
	await expect(drill).toBeVisible();
	await expect(drill.getByText('quality gate: row_count below floor')).toBeVisible();

	// The running run's drill-in shows its outputs + reproducibility pins on demand.
	await page.getByRole('button', { name: 'r-1' }).click();
	await expect(drill.getByRole('link', { name: 'silver$features' })).toBeVisible();
	await drill.getByRole('button', { name: 'reads' }).click();
	await expect(drill.getByText('bronze$events@1')).toBeVisible();

	// The text filter narrows the board.
	await page.getByPlaceholder('Filter runs…').fill('promote');
	await expect(rows).toHaveCount(1);
});

// ---- Columns (first-class view) ----

test('columns view: deep-link renders the field graph; clicking a field opens provenance/impact with the masking cue', async ({
	page,
}) => {
	// Column subgraph for silver$features: a masking derivation into pii_hash + a plain hop out.
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
	// Registered after beforeEach → these more-specific routes win for their URLs, leaving every
	// other /api call to the shared mock.
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

	// Deep-link with ?dataset= (the detail pages' "column lineage" link shape).
	await page.goto('/lineage/columns?dataset=silver%24features');
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

test('columns view without a dataset explains how to pick one', async ({ page }) => {
	await page.goto('/lineage/columns');
	await expect(page.getByText('Pick a dataset above', { exact: false })).toBeVisible();
	await expect(page.getByLabel('Dataset')).toBeVisible();
});

// ---- perf numbers (reported by the suite run) ----

test('graph + columns layout builds stay cheap (measured, printed to stdout)', async ({ page }) => {
	// Fill the graph to its MAX_GRAPH cap (60 datasets in one long derivation chain) so the
	// measured layout-build number is the worst case the canvas will render, not the 4-node demo.
	const BIG_NODES = Array.from({ length: 60 }, (_, i) => ({
		id: `ds_${i}`,
		namespace: 'perf',
		source_uri: `s3://lakehouse/ds_${i}`,
		tags: [],
	}));
	const BIG_EDGES = Array.from({ length: 59 }, (_, i) => ({
		source: `ds_${i + 1}`,
		target: `ds_${i}`,
		kind: 'derived_from',
	}));
	await page.route(
		(url) => url.pathname.endsWith('/lineage/api/graph'),
		(route) => json(route, { nodes: BIG_NODES, edges: BIG_EDGES, total: 60, capped: false }),
	);
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(60, { timeout: 20_000 });
	const graphMs = (await page.locator('header .perf').textContent()) ?? '?';

	await page.route('**/datasets/*/columns', (route) =>
		json(route, {
			root: 'silver$features',
			columns: [
				{ dataset: 'bronze$events', field: 'pii_email', type: 'string' },
				{ dataset: 'silver$features', field: 'pii_hash', type: 'string' },
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
			],
		}),
	);
	await page.goto('/lineage/columns?dataset=silver%24features');
	await expect(page.locator('.svelte-flow__node').first()).toBeVisible({ timeout: 15_000 });
	const colMs = (await page.locator('.canvas .perf').textContent()) ?? '?';

	console.log(`[perf] graph layout build: ${graphMs}; columns layout build: ${colMs}`);
	expect(graphMs).toMatch(/ms$/);
	expect(colMs).toMatch(/ms$/);
});

test('a flat 60-dataset estate packs into a square-ish grid, cheaply', async ({ page }) => {
	// The other worst case for the packer: 60 datasets, none derived from another — so all 60 are
	// depth-0 roots. They used to stack into one ~6600px column that fitView had to shrink to a
	// sliver; they must now wrap into ceil(sqrt(60)) = 8 columns.
	const FLAT_NODES = Array.from({ length: 60 }, (_, i) => ({
		id: `ds_${i}`,
		namespace: 'perf',
		source_uri: `s3://lakehouse/ds_${i}`,
		tags: [],
	}));
	await page.route(
		(url) => url.pathname.endsWith('/lineage/api/graph'),
		(route) => json(route, { nodes: FLAT_NODES, edges: [], total: 60, capped: false }),
	);
	await page.goto('/lineage');
	await expect(page.locator('.svelte-flow__node')).toHaveCount(60, { timeout: 20_000 });
	await page.waitForTimeout(700);

	const xs = new Set<number>();
	for (const node of await page.locator('.svelte-flow__node').all()) {
		xs.add(Math.round((await node.boundingBox())?.x ?? 0));
	}
	const flatMs = (await page.locator('header .perf').textContent()) ?? '?';
	console.log(`[perf] flat 60-root graph layout build: ${flatMs} (${xs.size} packed columns)`);
	expect(flatMs).toMatch(/ms$/);
	expect(xs.size).toBe(8);
});
