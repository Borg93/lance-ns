import { test, expect, type Route } from '@playwright/test';

// Hermetic /tables/<id> coverage (#64/#66/#65): the detail page's catalog calls go through the /capi BFF,
// stubbed here — no live catalog needed (same pattern as models.spec.ts). Guards the version-management
// surface the wrong-image deploy proved was unguarded: the manifest-per-commit version table, the branches
// row, the tag-a-version form, and the two-click restore control.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

const DETAIL = {
	describe: {
		version: 3,
		location: 's3://lance-catalog/db1$t',
		schema: {
			fields: [{ name: 'id', type: 'int64', nullable: false, metadata: { unit: 'count' } }],
		},
		metadata: { owner: 'data-eng' }, // #74 tail — table-level schema metadata (properties editor seed)
	},
	stats: { num_rows: 100, total_bytes: 2048, num_indices: 1 },
	versions: {
		versions: [
			{ version: 1, timestamp_millis: 1_700_000_000_000, manifest_size: 512 },
			{ version: 2, timestamp_millis: 1_700_000_100_000, manifest_size: 1024 },
			{ version: 3, timestamp_millis: 1_700_000_200_000, manifest_size: 2048 },
		],
	},
	tags: { tags: { blessed: { version: 2 } } },
	branches: {
		branches: {
			main: { createAt: 1_700_000_000, manifestSize: 512 },
			dev: { createAt: 1_700_000_100, manifestSize: 1024 },
		},
	},
	indexes: { indexes: [{ index_name: 'id_idx', columns: ['id'], index_type: 'BTREE' }] },
	policy: {
		retention_days: 7,
		retain_versions: 5,
		compact_enabled: true,
		target_rows_per_fragment: 1048576,
	},
	format: { name: 'Lance', storage_version: '2.2' },
};

// The writes the interaction tests make; recorded so we can assert the BFF POST fired with the right body.
let tagPost: { tag: string; version: number } | null;
let restorePost: { version: number } | null;
let insertPostBytes: number;
let indexCreate: { url: string; body: Record<string, unknown> } | null;
let indexDrop: string | null;
let gcPreviewBody: Record<string, unknown> | null;
let gcRan: boolean;
let compactBody: Record<string, unknown> | null;
let colPost: { op: string; body: Record<string, unknown> } | null;
let refPost: { path: string; body: Record<string, unknown> } | null;
// scope #6 — the latest producing run(s) for the quality badge; the lineage /api proxy is stubbed with this.
let producersFixture: Array<Record<string, unknown>>;

test.beforeEach(async ({ page }) => {
	colPost = null;
	refPost = null;
	tagPost = null;
	restorePost = null;
	insertPostBytes = 0;
	indexCreate = null;
	indexDrop = null;
	gcPreviewBody = null;
	gcRan = false;
	compactBody = null;
	producersFixture = []; // default: no quality-bearing runs → honest "no quality gate"
	// The #6 quality badge reads producing runs through the lineage BFF; stub it to stay hermetic.
	await page.route('**/api/datasets/**/producers', (route) =>
		json(route, { producers: producersFixture }),
	);
	await page.route('**/capi/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^\/capi/, '');
		if (path.endsWith('/detail')) return json(route, DETAIL);
		if (path.endsWith('/tags') && req.method() === 'POST') {
			tagPost = req.postDataJSON() as { tag: string; version: number };
			return json(route, { tag: tagPost.tag, version: tagPost.version });
		}
		if (path.endsWith('/restore') && req.method() === 'POST') {
			restorePost = req.postDataJSON() as { version: number };
			return json(route, { version: 4 });
		}
		if (path.endsWith('/insert') && req.method() === 'POST') {
			// The body is a browser-built Arrow-IPC stream — assert it's non-empty binary, not JSON.
			insertPostBytes = req.postDataBuffer()?.length ?? 0;
			return json(route, { transaction_id: 'tx1' });
		}
		if (path.includes('/index/create')) {
			indexCreate = { url: req.url(), body: req.postDataJSON() as Record<string, unknown> };
			return json(route, { transaction_id: 'ix1' });
		}
		if (path.match(/\/index\/[^/]+\/drop$/) && req.method() === 'POST') {
			indexDrop = path;
			return json(route, { transaction_id: 'ix2' });
		}
		if (path.endsWith('/maintenance/preview')) {
			gcPreviewBody = req.postDataJSON() as Record<string, unknown>;
			return json(route, {
				current_version: 3,
				total_versions: 3,
				eligible_versions: [1],
				protected_tags: { blessed: 2 },
				retention_days: null,
				retain_versions: 2,
			});
		}
		if (path.endsWith('/maintenance/run')) {
			gcRan = true;
			return json(route, { ok: true, old_versions_removed: 1, bytes_removed: 512 });
		}
		if (path.endsWith('/maintenance/compact')) {
			compactBody = req.postDataJSON() as Record<string, unknown>;
			return json(route, { ok: true, fragments_removed: 6, fragments_added: 1 });
		}
		if (
			path.match(/\/columns\/(add|alter|drop|field-meta|table-meta)$/) &&
			req.method() === 'POST'
		) {
			colPost = {
				op: path.split('/').pop() ?? '',
				body: req.postDataJSON() as Record<string, unknown>,
			};
			return json(route, { version: 4 });
		}
		const ref = path.match(/\/(branches|tags)\/(create|delete|update)$/);
		if (ref && req.method() === 'POST') {
			refPost = {
				path: `${ref[1]}/${ref[2]}`,
				body: req.postDataJSON() as Record<string, unknown>,
			};
			return json(route, { version: 5 });
		}
		return json(route, { detail: 'unstubbed' }, 404);
	});
});

test('renders the manifest-per-commit version table, branches, and tags (#66)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	await expect(page.getByRole('heading', { name: 'db1$t' })).toBeVisible();
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	// newest-first version rows with the manifest size surfaced
	await expect(section.locator('tbody tr').first()).toContainText('v3');
	await expect(section.locator('tbody tr').first()).toContainText('2.0 KiB');
	await expect(section).toContainText('v1');
	// branches row + the tag chip
	await expect(section).toContainText('main');
	await expect(section).toContainText('blessed → v2');
	// indexes section (#64)
	const indexes = page.locator('section', { hasText: 'Indexes' });
	await expect(indexes).toContainText('id_idx');
	await expect(indexes).toContainText('BTREE');
});

test('tag-a-version form posts {tag, version} through the BFF (#64)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	await section.getByPlaceholder('tag name (e.g. blessed)').fill('release-1');
	// the version picker is the @lance/ui Select (bits-ui) — open it, then click the option
	await section.getByLabel('Version to tag').click();
	await page.getByRole('option', { name: 'v3', exact: true }).click();
	await section.getByRole('button', { name: 'Tag version' }).click();
	await expect.poll(() => tagPost).toEqual({ tag: 'release-1', version: 3 });
});

test('restore is a two-click confirm and posts {version} (#64)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	const firstRow = section.locator('tbody tr').first(); // v3
	await firstRow.getByRole('button', { name: 'restore' }).click();
	// first click only arms the confirm — no write yet
	expect(restorePost).toBeNull();
	await firstRow.getByRole('button', { name: 'confirm restore' }).click();
	await expect.poll(() => restorePost).toEqual({ version: 3 });
});

test('insert-rows form encodes JSON to an Arrow-IPC body and posts to /insert (#64)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Insert rows' });
	await section.locator('textarea.ins').fill('[{ "id": 9, "name": "z" }]');
	await section.getByRole('button', { name: 'Insert' }).click();
	// the browser encoded the rows to a non-empty Arrow-IPC binary body (apache-arrow), not JSON
	await expect.poll(() => insertPostBytes).toBeGreaterThan(0);
	await expect(section).toContainText('Inserted 1 row');
});

test('builds a vector index through the create form (#73)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Indexes' });
	await section.getByLabel('Index column').fill('vec');
	await section.getByLabel('Index type').click();
	await page.getByRole('option', { name: 'vector · IVF_PQ' }).click();
	await section.getByRole('button', { name: 'Build index' }).click();
	// a vector type routes to create_index (scalar=0) and carries the distance type
	await expect
		.poll(() => indexCreate?.body)
		.toEqual({ column: 'vec', index_type: 'IVF_PQ', distance_type: 'cosine' });
	expect(indexCreate?.url).toContain('scalar=0');
});

test('drops an index via the chip × (#73)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Indexes' });
	await section.getByRole('button', { name: 'drop index id_idx' }).click();
	await expect.poll(() => indexDrop).toContain('/index/id_idx/drop');
});

test('GC preview lists reclaimable versions + protected tags (#75)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Maintenance policy' });
	await section.getByRole('spinbutton', { name: 'keep last' }).fill('2');
	await section.getByRole('button', { name: 'Preview' }).click();
	await expect(section.locator('.gc')).toContainText('1 version reclaimable');
	await expect(section.locator('.gc')).toContainText('blessed→v2'); // tag protection surfaced
	expect(gcPreviewBody).toEqual({ retention_days: null, retain_versions: 2 });
});

test('GC reclaim is a two-click confirm and posts to /maintenance/run (#75)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const gc = page.locator('section', { hasText: 'Maintenance policy' }).locator('.gc');
	await gc.getByRole('spinbutton', { name: 'keep last' }).fill('2');
	await gc.getByRole('button', { name: 'Preview' }).click();
	await gc.getByRole('button', { name: 'Reclaim now' }).click();
	// first click only arms the confirm — no run yet
	expect(gcRan).toBe(false);
	await gc.getByRole('button', { name: 'Confirm reclaim' }).click();
	await expect.poll(() => gcRan).toBe(true);
	await expect(gc).toContainText('Reclaimed 1 version');
});

test('compact-now posts to /maintenance/compact with the policy target size (#76)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	const gc = page.locator('section', { hasText: 'Maintenance policy' }).locator('.gc');
	await gc.getByRole('button', { name: 'Compact now' }).click();
	await expect.poll(() => compactBody).toEqual({ target_rows_per_fragment: 1048576 });
	await expect(gc).toContainText('6 fragment'); // "Compacted · 6 fragment(s) → 1."
});

test('the policy surfaces the compaction target size (#76)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Maintenance policy' });
	await expect(section).toContainText('target 1048576 rows/frag');
});

test('add-column posts a SQL-expression column (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByLabel('New column name').fill('doubled');
	await section.getByLabel('Column SQL expression').fill('id * 2');
	await section.getByRole('button', { name: 'Add column' }).click();
	await expect.poll(() => colPost?.op).toBe('add');
	expect(colPost?.body).toEqual({ new_columns: [{ name: 'doubled', expression: 'id * 2' }] });
});

test('drop-column via the row × posts {columns} (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByRole('button', { name: 'drop id' }).click();
	await expect.poll(() => colPost?.op).toBe('drop');
	expect(colPost?.body).toEqual({ columns: ['id'] });
});

test('rename-column via the row ✎ posts an alter path→rename (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByRole('button', { name: 'rename id' }).click();
	await section.getByLabel('rename id to').fill('identifier');
	await section.getByRole('button', { name: 'save' }).click();
	await expect.poll(() => colPost?.op).toBe('alter');
	expect(colPost?.body).toEqual({ alterations: [{ path: 'id', rename: 'identifier' }] });
});

test('re-type-column via the row ⇄ posts an alter path→data_type (#74 tail)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByRole('button', { name: 're-type id' }).click();
	// the target type is the @lance/ui Select (bits-ui) — open it, pick float32
	await section.getByLabel('re-type id to').click();
	await page.getByRole('option', { name: 'float32', exact: true }).click();
	await section.getByRole('button', { name: 'save' }).click();
	await expect.poll(() => colPost?.op).toBe('alter');
	expect(colPost?.body).toEqual({ alterations: [{ path: 'id', data_type: { type: 'float32' } }] });
});

test('save table properties posts the full metadata map (#74 tail)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Properties' });
	// the seed row is describe.metadata { owner: "data-eng" }; add a second key, then save the whole map
	await section.getByRole('button', { name: '+ add row' }).click();
	await section.getByLabel('Property key 2').fill('tier');
	await section.getByLabel('Property value 2').fill('gold');
	await section.getByRole('button', { name: 'Save properties' }).click();
	await expect.poll(() => colPost?.op).toBe('table-meta');
	expect(colPost?.body).toEqual({ metadata: { owner: 'data-eng', tier: 'gold' } });
	await expect(section.getByText('Saved.')).toBeVisible();
});

test('set a column property merges one key (#74 tail)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Properties' });
	await section.getByLabel('Column for properties').click();
	await page.getByRole('option', { name: 'id', exact: true }).click();
	// the seeded field metadata { unit: "count" } renders as a deletable chip
	await expect(section).toContainText('unit=count');
	await section.getByLabel('Column property key').fill('pii');
	await section.getByLabel('Column property value').fill('false');
	await section.getByRole('button', { name: 'Set', exact: true }).click();
	await expect.poll(() => colPost?.op).toBe('field-meta');
	expect(colPost?.body).toEqual({
		updates: [{ path: 'id', metadata: { pii: 'false' }, replace: false }],
	});
});

test('delete a column property posts a null-valued key (#74 tail)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Properties' });
	await section.getByLabel('Column for properties').click();
	await page.getByRole('option', { name: 'id', exact: true }).click();
	await section.getByRole('button', { name: 'Delete column property unit' }).click();
	await expect.poll(() => colPost?.op).toBe('field-meta');
	expect(colPost?.body).toEqual({
		updates: [{ path: 'id', metadata: { unit: null }, replace: false }],
	});
});

test('delete a tag via the chip × (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	await section.getByRole('button', { name: 'delete tag blessed' }).click();
	await expect.poll(() => refPost?.path).toBe('tags/delete');
	expect(refPost?.body).toEqual({ tag: 'blessed' });
});

test('move a tag to another version (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	await section.getByRole('button', { name: 'move tag blessed' }).click();
	await section.getByLabel('move blessed to version').click();
	await page.getByRole('option', { name: 'v3', exact: true }).click();
	await section.getByRole('button', { name: 'save' }).click();
	await expect.poll(() => refPost?.path).toBe('tags/update');
	expect(refPost?.body).toEqual({ tag: 'blessed', version: 3 });
});

test('create a branch from a version (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	await section.getByLabel('New branch name').fill('feature');
	await section.getByLabel('Branch from version').click();
	await page.getByRole('option', { name: 'v2', exact: true }).click();
	await section.getByRole('button', { name: 'Create branch' }).click();
	await expect.poll(() => refPost?.path).toBe('branches/create');
	expect(refPost?.body).toEqual({ name: 'feature', from_version: 2 });
});

test('delete a branch via the chip × (#74)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Versions, branches & tags' });
	await section.getByRole('button', { name: 'delete branch dev' }).click();
	await expect.poll(() => refPost?.path).toBe('branches/delete');
	expect(refPost?.body).toEqual({ name: 'dev' });
});

test('surfaces the Lance file format badge (#78)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const stats = page.locator('section', { hasText: 'Stats' }).first();
	await expect(stats).toContainText('Lance · storage v2.2');
});

test('surfaces the validator quality gate when a run passed it (#82)', async ({ page }) => {
	producersFixture = [
		{ run_id: 'r1', quality_passed: true, quality_assertions: [{ assertion: 'row_count' }] },
	];
	await page.goto('/data/tables/db1%24t');
	const stats = page.locator('section', { hasText: 'Stats' }).first();
	await expect(stats).toContainText('quality passed · 1 check');
});

test('surfaces a blocked quality gate (#82)', async ({ page }) => {
	producersFixture = [
		{
			run_id: 'r1',
			quality_passed: false,
			quality_assertions: [{ assertion: 'not_null' }, { assertion: 'unique' }],
		},
	];
	await page.goto('/data/tables/db1%24t');
	const stats = page.locator('section', { hasText: 'Stats' }).first();
	await expect(stats).toContainText('quality blocked · 2 checks');
});

test("states 'no quality gate' honestly when no run recorded assertions (#82)", async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t'); // producersFixture defaults to []
	const stats = page.locator('section', { hasText: 'Stats' }).first();
	await expect(stats).toContainText('no quality gate');
});
