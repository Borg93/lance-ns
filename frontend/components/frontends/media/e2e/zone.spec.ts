import { test, expect, type Route } from '@playwright/test';

// Hermetic coverage for the zone contract: SSR on at the app level, the client fetching
// the media plane through THIS zone's base-prefixed BFF routes (/media/api/*, /media/capi/*)
// instead of the retired root-absolute /api/*. Every backend response is mocked in the
// browser; the dev server still runs the real SSR + hooks + BFF endpoints.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

// The descriptor-store boot ritual: /api/health names the default DB → its descriptor.
const HEALTH = {
	db: { path: '/data/demo.lance', tables: ['chunks'], chunks: 2, documents: 1 },
	embed: { ok: true, url: 'http://embed', error: null },
	rerank: { ok: true, url: 'http://rerank', error: null },
};

const col = (name: string, arrow_type: string) => ({
	name,
	arrow_type,
	nullable: true,
	vector_dim: null,
	is_blob: false,
});

const DESCRIPTOR = {
	id: 'demo',
	tables: {
		chunks: {
			name: 'chunks',
			row_count: 2,
			version: 1,
			columns: [
				col('doc_id', 'string'),
				col('speech_id', 'int64'),
				col('chunk_id', 'int64'),
				col('title', 'string'),
				col('text', 'string'),
			],
			indexes: [],
		},
	},
	declared: {
		identity: { key_fields: ['doc_id', 'speech_id', 'chunk_id'], doc_key: 'doc_id' },
		document: null,
		time: null,
		display: { title: ['title'], body: 'text', caption: null, metadata: [] },
		search: {
			row_table: 'chunks',
			fts: { table: 'chunks', column: 'text' },
			vectors: {},
			filterable: [],
			rerank: false,
		},
		atlas: [],
		capabilities: {},
	},
};

const HIT = {
	doc_id: 'd1',
	speech_id: 0,
	chunk_id: 0,
	title: 'Hello world',
	text: 'the quick brown fox jumps',
	_score: 3.2,
	alignments: [],
};

let apiPaths: string[] = [];

test.beforeEach(async ({ page }) => {
	apiPaths = [];
	// Zone-scoped globs on purpose: a bare **/api/** also matches Vite /@fs module URLs
	// (…/packages/api/…) and would kill hydration. Registration order is LIFO — the
	// generic 404 first, the specific mocks after so they win.
	await page.route('**/media/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.route('**/media/api/**', (route) => {
		apiPaths.push(new URL(route.request().url()).pathname);
		return json(route, { detail: 'unstubbed' }, 404);
	});
	await page.route('**/media/api/health', (route) => {
		apiPaths.push(new URL(route.request().url()).pathname);
		return json(route, HEALTH);
	});
	await page.route('**/media/api/datasets/demo/descriptor', (route) => {
		apiPaths.push(new URL(route.request().url()).pathname);
		return json(route, DESCRIPTOR);
	});
	await page.route('**/media/api/search**', (route) => {
		apiPaths.push(new URL(route.request().url()).pathname);
		return json(route, [HIT]);
	});
});

test('the app server-renders under /media (SSR on, hooks answering)', async ({ page }) => {
	// A raw server response (no JS runs through the request API): the layout shell must
	// arrive server-rendered — the pre-descriptor loading state proves real SSR output.
	const res = await page.request.get('/media/');
	expect(res.status()).toBe(200);
	expect(await res.text()).toContain('Loading dataset');
});

test('boots the descriptor + searches through the zone-based BFF paths', async ({ page }) => {
	await page.goto('/media/');
	// Hydrated shell: the estate sidebar renders once the (mocked) descriptor lands.
	await expect(page.getByRole('link', { name: 'Atlas' })).toBeVisible();
	// The boot fetches went to /media/api/* — the base-prefixed BFF, never bare /api.
	await expect.poll(() => apiPaths).toContain('/media/api/health');
	await expect.poll(() => apiPaths).toContain('/media/api/datasets/demo/descriptor');
	// Drive a search; the mocked hit renders through the descriptor-driven view.
	const input = page.getByPlaceholder(/Search transcripts/);
	await input.fill('fox');
	await input.press('Enter');
	await expect(page.getByText('Hello world').first()).toBeVisible();
	await expect
		.poll(() => apiPaths.filter((p) => p.startsWith('/media/api/search')))
		.not.toHaveLength(0);
});
