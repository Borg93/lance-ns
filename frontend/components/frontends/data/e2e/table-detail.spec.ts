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
// #85 danger zone + row ops — the lifecycle writes (drop/deregister have no body; rename carries one)
// and the predicate-scoped update/delete, each recorded with the EXACT stripped /capi path so the wire
// contract (incl. the %24 id encoding) is pinned, never guessed.
let dropPath: string | null;
let deregisterPath: string | null;
let renamePost: { path: string; body: Record<string, unknown> } | null;
let rowPost: { op: string; body: Record<string, unknown> } | null;
// The registry list the post-drop navigation re-lists (GET /v1/table).
let registryTables: string[];
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
	dropPath = null;
	deregisterPath = null;
	renamePost = null;
	rowPost = null;
	registryTables = ['db1$t', 'db1$other'];
	producersFixture = []; // default: no quality-bearing runs → honest "no quality gate"
	// The #6 quality badge reads producing runs through the lineage BFF; stub it to stay hermetic.
	await page.route('**/api/datasets/**/producers', (route) =>
		json(route, { producers: producersFixture }),
	);
	await page.route('**/capi/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/capi/, '');
		if (path.endsWith('/detail')) return json(route, DETAIL);
		if (path === '/v1/table') return json(route, { tables: registryTables });
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
			path.match(/\/columns\/(add|alter|drop|backfill|field-meta|table-meta)$/) &&
			req.method() === 'POST'
		) {
			colPost = {
				op: path.split('/').pop() ?? '',
				body: req.postDataJSON() as Record<string, unknown>,
			};
			// backfill is the async native job — its response is a job_id, not a version
			return json(route, path.endsWith('/backfill') ? { job_id: 'j1' } : { version: 4 });
		}
		// #85 lifecycle + row ops — anchored regexes, NOT endsWith: '/index/…/drop' and '/columns/drop'
		// also end with '/drop' and must keep hitting their own stubs above.
		if (/^\/v1\/table\/[^/]+\/drop$/.test(path) && req.method() === 'POST') {
			dropPath = path;
			return json(route, { id: ['db1', 't'] });
		}
		if (/^\/v1\/table\/[^/]+\/deregister$/.test(path) && req.method() === 'POST') {
			deregisterPath = path;
			return json(route, { id: ['db1', 't'], location: 's3://lance-catalog/db1$t' });
		}
		if (/^\/v1\/table\/[^/]+\/rename$/.test(path) && req.method() === 'POST') {
			renamePost = { path, body: req.postDataJSON() as Record<string, unknown> };
			return json(route, {});
		}
		if (/^\/v1\/table\/[^/]+\/update$/.test(path) && req.method() === 'POST') {
			rowPost = { op: 'update', body: req.postDataJSON() as Record<string, unknown> };
			return json(route, { updated_rows: 2, version: 4 });
		}
		if (/^\/v1\/table\/[^/]+\/delete$/.test(path) && req.method() === 'POST') {
			rowPost = { op: 'delete', body: req.postDataJSON() as Record<string, unknown> };
			return json(route, { version: 5 });
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
	// the version picker is the @rask/ui Select (bits-ui) — open it, then click the option
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
	// the target type is the @rask/ui Select (bits-ui) — open it, pick float32
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

// --- #85 danger zone: drop / deregister (AlertDialog confirm) + rename (navigates) ---

test('danger-zone drop confirms via the AlertDialog, closes it, and the registry row is gone (#85)', async ({
	page,
}) => {
	registryTables = ['db1$other']; // the post-drop world the registry re-lists after navigation
	await page.goto('/data/tables/db1%24t');
	const danger = page.locator('section.dangerzone');
	await danger.getByRole('button', { name: 'Drop table' }).click();
	// The confirm is the portalled @rask/ui AlertDialog — drive it by role, not the trigger section.
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('Drop table db1$t');
	await dialog.getByRole('button', { name: 'Drop', exact: true }).click();
	// The exact wire path, %24-encoded id included — poll, don't race the interception.
	await expect.poll(() => dropPath).toBe('/v1/table/db1%24t/drop');
	// The dialog must CLOSE after the drop — a still-open dialog keeps the destructive action armed
	// for a second, confirm-free fire (the NamespaceRegistry audit fix, copied here).
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
	// The id no longer names a table — back to the registry, where the dropped row is gone.
	await expect(page).toHaveURL(/\/data\/tables$/);
	await expect(page.getByRole('link', { name: 'db1$other' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'db1$t', exact: true })).toHaveCount(0);
});

test('danger-zone deregister confirms via its own AlertDialog copy (#85)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	await page.locator('section.dangerzone').getByRole('button', { name: 'Deregister' }).click();
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('Deregister table db1$t');
	await expect(dialog).toContainText('data stays on storage'); // deregister ≠ drop, stated honestly
	await dialog.getByRole('button', { name: 'Deregister', exact: true }).click();
	await expect.poll(() => deregisterPath).toBe('/v1/table/db1%24t/deregister');
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
	await expect(page).toHaveURL(/\/data\/tables$/);
});

test('cancelling the danger-zone confirm never posts (#85)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	await page.locator('section.dangerzone').getByRole('button', { name: 'Drop table' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click();
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
	expect(dropPath).toBeNull();
	// still on the detail page — nothing was dropped
	await expect(page).toHaveURL(/\/data\/tables\/db1%24t$/);
});

test('a 403 drop surfaces the owner-denied state and stays on the page (#85)', async ({ page }) => {
	// A later page.route wins over the beforeEach glob — deny like the catalog's FGA gate (can_drop).
	await page.route('**/capi/v1/table/*/drop', (route) => json(route, { detail: 'forbidden' }, 403));
	await page.goto('/data/tables/db1%24t');
	const danger = page.locator('section.dangerzone');
	await danger.getByRole('button', { name: 'Drop table' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: 'Drop', exact: true }).click();
	await expect(danger).toContainText('Denied: drop needs the owner rung (can_drop).');
	await expect(page.getByRole('alertdialog')).toHaveCount(0); // closed even on failure (finally)
	await expect(page).toHaveURL(/\/data\/tables\/db1%24t$/);
});

test('rename posts {new_table_name} and navigates to the renamed detail (#85)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	const danger = page.locator('section.dangerzone');
	await danger.getByLabel('Rename table to').fill('t2');
	await danger.getByRole('button', { name: 'Rename' }).click();
	// The exact wire body: the catalog's RenameTableRequest carries new_table_name (namespace kept).
	await expect
		.poll(() => renamePost)
		.toEqual({ path: '/v1/table/db1%24t/rename', body: { new_table_name: 't2' } });
	// success navigates to the renamed table's detail (the old id no longer exists)
	await expect(page).toHaveURL(/\/data\/tables\/db1%24t2$/);
	await expect(page.getByRole('heading', { name: 'db1$t2' })).toBeVisible();
});

// --- #85 row ops: update / delete by SQL predicate ---

test('update rows posts the exact {predicate, updates} wire body and surfaces the count (#85)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Update / delete rows' });
	await section.getByLabel('Row predicate').fill('id > 3');
	await section.getByLabel('SET column 1').fill('name');
	await section.getByLabel('SET expression 1').fill("'x'");
	await section.getByRole('button', { name: 'Update rows' }).click();
	// UpdateTableRequest on the wire: updates = [[column, expression], …] pairs + the predicate.
	await expect
		.poll(() => rowPost)
		.toEqual({ op: 'update', body: { predicate: 'id > 3', updates: [['name', "'x'"]] } });
	// updated_rows + version are REQUIRED on the wire — the affected-row count surfaces
	await expect(section).toContainText('Updated 2 rows → v4.');
});

test('update with an empty predicate omits the key (all rows) (#85)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Update / delete rows' });
	await section.getByLabel('SET column 1').fill('flag');
	await section.getByLabel('SET expression 1').fill('true');
	await section.getByRole('button', { name: 'Update rows' }).click();
	// no predicate key at all — an empty-string predicate is not the same wire contract
	await expect.poll(() => rowPost).toEqual({ op: 'update', body: { updates: [['flag', 'true']] } });
});

test('delete rows is a two-click confirm and posts {predicate} only (#85)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Update / delete rows' });
	await section.getByLabel('Row predicate').fill('id = 9');
	await section.getByRole('button', { name: 'Delete rows' }).click();
	// first click only arms the confirm — no write yet
	expect(rowPost).toBeNull();
	await section.getByRole('button', { name: 'confirm delete' }).click();
	// DeleteFromTableRequest on the wire: predicate REQUIRED, nothing else
	await expect.poll(() => rowPost).toEqual({ op: 'delete', body: { predicate: 'id = 9' } });
	// the delete wire has no row count — the new version is surfaced honestly instead
	await expect(section).toContainText('Deleted rows matching the predicate → v5.');
});

test('a 403 row update renders the writer-denied state (#85)', async ({ page }) => {
	await page.route('**/capi/v1/table/*/update', (route) =>
		json(route, { detail: 'forbidden' }, 403),
	);
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Update / delete rows' });
	await section.getByLabel('SET column 1').fill('name');
	await section.getByLabel('SET expression 1').fill("'x'");
	await section.getByRole('button', { name: 'Update rows' }).click();
	await expect(section).toContainText('Denied: row changes need writer access (can_write_data).');
});

// --- #85 backfill_column: the async columns op beside add/alter/drop ---

test('backfill posts {column, where} through the columns allowlist and surfaces the job id (#85)', async ({
	page,
}) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByRole('button', { name: 'backfill id' }).click();
	await section.getByLabel('backfill id where').fill('id > 0');
	await section.getByRole('button', { name: 'run' }).click();
	await expect.poll(() => colPost?.op).toBe('backfill');
	expect(colPost?.body).toEqual({ column: 'id', where: 'id > 0' });
	// async job — the UI surfaces the job_id (no version to refresh yet)
	await expect(section).toContainText('Backfill of id started · job j1.');
});

test('backfill with no predicate omits the where key (#85)', async ({ page }) => {
	await page.goto('/data/tables/db1%24t');
	const section = page.locator('section', { hasText: 'Schema' }).first();
	await section.getByRole('button', { name: 'backfill id' }).click();
	await section.getByRole('button', { name: 'run' }).click();
	await expect.poll(() => colPost?.op).toBe('backfill');
	expect(colPost?.body).toEqual({ column: 'id' });
});
