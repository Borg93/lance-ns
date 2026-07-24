import { test, expect, type Route } from '@playwright/test';

// Hermetic coverage for the zone contract: the app is server-aware (hooks + BFF routes
// answer under /annotator; only the Pixi canvas page itself opts out of SSR per-page),
// and the client fetches the media plane through THIS zone's base-prefixed BFF routes
// (/annotator/api/*) instead of the retired root-absolute /api/*.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

// 1×1 transparent PNG for the demo unit's chunk-frame.
const PNG = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
	'base64',
);

let apiPaths: string[] = [];
let apiWrites: string[] = [];

test.beforeEach(async ({ page }) => {
	apiPaths = [];
	apiWrites = [];
	// Zone-scoped globs on purpose: a bare **/api/** also matches Vite /@fs module URLs
	// (…/packages/api/…) and would kill hydration. Registration order is LIFO — the
	// generic 404 first, the specific mocks after so they win.
	await page.route('**/annotator/capi/v1/me', (route) => json(route, { detail: 'anon' }, 401));
	await page.route('**/annotator/api/**', (route) => {
		const req = route.request();
		apiPaths.push(new URL(req.url()).pathname);
		if (req.method() !== 'GET') apiWrites.push(new URL(req.url()).pathname);
		return json(route, { detail: 'unstubbed' }, 404);
	});
	await page.route('**/annotator/api/chunk-frame/**', (route) => {
		apiPaths.push(new URL(route.request().url()).pathname);
		return route.fulfill({ status: 200, contentType: 'image/png', body: PNG });
	});
	// The annotations GET 404s: the controller's documented soft-fail path (empty unit),
	// which keeps this hermetic without fabricating an Arrow IPC payload.
});

test('the server answers under /annotator (hooks live; canvas page opts out per-page)', async ({
	page,
}) => {
	const res = await page.request.get('/annotator/');
	expect(res.status()).toBe(200);
	// The page itself is a per-page ssr=false island, but it is SERVED by the SvelteKit
	// server under the zone base — the kit-injected config must carry the based path
	// (dev serves modules at /annotator/@fs, the build at /annotator/_app).
	expect(await res.text()).toContain('base: "/annotator"');
});

test('boots the shell and loads the unit through the zone-based BFF paths', async ({ page }) => {
	await page.goto('/annotator/');
	// The estate navbar (layout) renders; the toolbar's stable controls mount.
	await expect(page.getByTitle('Redo (Ctrl+Shift+Z)')).toBeVisible();
	// The demo unit's annotations were requested via /annotator/api/* — the base-prefixed
	// BFF, never bare /api — and nothing fired a write on boot.
	await expect.poll(() => apiPaths).toContain('/annotator/api/annotations/fe00cd746463ad2c/0/19');
	expect(apiWrites).toHaveLength(0);
});
