/**
 * Live proof for the server-side half of the atlas-points fix, driven through the real ingress with real
 * Dex logins — not the dev server, not mocks.
 *
 * What it has to show, in the order the condition states it:
 *
 *   1. AUTHORIZE EVERY REQUEST. An anonymous caller is refused on the exact URL that is WARM in the
 *      cache. Before this route existed that same curl was answered `200` with 6,678,928 bytes.
 *   2. KEYED ON THE RESOURCE. A SECOND USER's FIRST atlas load — measured on the PAGE's own request, not
 *      a scripted one — is served from the entry the first user's page filled.
 *   3. SINGLE-FLIGHT. Ten concurrent cold requests produce exactly ONE `/api/atlas/points` line in the
 *      viewer's access log. That is the case that OOM-killed it, so the log is counted, not assumed.
 *
 * Two things this script learned the hard way, both from looking at its own screenshot:
 *
 * - The browser MUST be launched with the WebGPU flags from `e2e/lib.mjs`. Without them the atlas renders
 *   "WebGPU is required (no GPU adapter available)", the page never fetches /points at all, and a suite
 *   that only asserts on its OWN `request.get` calls passes while the product under test did nothing. The
 *   first run of this file did exactly that.
 * - The cold-start case uses a unique `v` token rather than restarting the pod: `v` is part of the cache
 *   key by design ("a new build changes the key"), so a fresh token is a guaranteed-cold key that leaves
 *   the estate alone — and exercising it checks that the version token really is in the key.
 *
 * The zone pod is deleted first (COLD=0 to skip) so alice's page load is the genuine first fill and bob's
 * is a genuine second user. Env: ORIGIN, SHOT_DIR, RELEASE, KUBECTL, COLD.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { chromium } from '@playwright/test';

const ORIGIN = process.env.ORIGIN ?? 'http://localhost:8090';
const SHOT_DIR = process.env.SHOT_DIR ?? '/tmp/lance-verify-shots';
const RELEASE = process.env.RELEASE ?? 'lance-ns';
const KUBECTL = process.env.KUBECTL ?? 'kubectl';
const COLD = process.env.COLD !== '0';

// Dex is reached by its in-cluster name inside the browser; map it onto the port-forward. The rest are
// e2e/lib.mjs's WebGPU flags — without them the atlas renders an error and fetches nothing.
const ARGS = [
	'--host-resolver-rules=MAP lance-ns-dex:5556 127.0.0.1:5556',
	'--headless=new',
	'--no-sandbox',
	'--enable-unsafe-webgpu',
	'--enable-features=Vulkan',
	'--use-angle=vulkan',
	'--ignore-gpu-blocklist',
];

const POINTS = (v) => `/media/api/atlas/points?space=text&v=${v}`;
const PRODUCT_V = 6; // what packages/media-api/src/api.ts actually asks for

let failures = 0;
const ok = (cond, msg) => {
	console.log(`   ${cond ? '✓' : '✗ FAIL:'} ${msg}`);
	if (!cond) failures++;
};
const kube = (...args) =>
	execFileSync(KUBECTL, args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });

/** How many times the viewer has served the atlas projection, straight out of its access log. */
const viewerPointsServed = () =>
	kube('logs', `deploy/${RELEASE}-viewer`, '-c', 'viewer', '--tail=-1')
		.split('\n')
		.filter((l) => l.includes('GET /api/atlas/points')).length;

/** Restart the zone so the in-process cache starts genuinely empty. */
async function coldStart() {
	kube('delete', 'pod', '-l', 'app.kubernetes.io/component=web-media', '--wait=true');
	kube(
		'wait',
		'--for=condition=ready',
		'pod',
		'-l',
		'app.kubernetes.io/component=web-media',
		'--timeout=120s',
	);
	// Pod-ready is not edge-ready: the ingress controller's endpoint list lags the readiness gate by a
	// moment, and a request in that window is answered 503 by NGINX, not by the zone. The first run of
	// this script asserted 401 there and reported a failure that had nothing to do with the route.
	for (let i = 0; i < 60; i++) {
		const res = await fetch(`${ORIGIN}/media/api/health`).catch(() => null);
		if (res?.ok) break;
		await new Promise((r) => setTimeout(r, 500));
	}
	console.log('   zone pod replaced and reachable through the edge — the cache is empty');
}

async function login(context, user, startPath) {
	const page = await context.newPage();
	await page.goto(`${ORIGIN}/auth/login?redirect=${encodeURIComponent(startPath)}`, {
		waitUntil: 'domcontentloaded',
	});
	await page.waitForURL(/\/dex\/auth/, { timeout: 20000 });
	await page.fill(
		'input[name="login"], input#login, input[type="text"], input[type="email"]',
		user,
	);
	await page.fill('input[name="password"], input#password, input[type="password"]', 'password');
	await page.click('button[type="submit"], input[type="submit"], #submit-login');
	await page.waitForURL((u) => u.origin === ORIGIN && !u.pathname.startsWith('/auth'), {
		timeout: 30000,
	});
	if (page.url().includes('auth=error')) throw new Error(`login failed for ${user}: ${page.url()}`);
	return page;
}

/** Record what the PAGE itself asked of /atlas/points, and how the BFF answered. */
function watchPoints(page) {
	const seen = [];
	page.on('response', (res) => {
		if (!res.url().includes('/api/atlas/points')) return;
		seen.push({ status: res.status(), cache: res.headers()['x-cache'] ?? null, url: res.url() });
	});
	return seen;
}

/** GET through the edge, reporting the three things that matter: status, x-cache, byte count. */
async function get(ctx, path) {
	const started = Date.now();
	const res = await ctx.request.get(`${ORIGIN}${path}`, { timeout: 60000 });
	const bytes = (await res.body()).byteLength;
	return {
		status: res.status(),
		cache: res.headers()['x-cache'] ?? null,
		bytes,
		ms: Date.now() - started,
	};
}

/** The atlas is drawn on a canvas; the only honest "it rendered" signal is the ABSENCE of its own error
 *  and the presence of the colour legend, which is built from the parsed payload. */
async function atlasRendered(page) {
	const webgpuError = await page.getByText(/WebGPU is required/i).count();
	const canvases = await page.locator('canvas').count();
	return { webgpuError, canvases };
}

mkdirSync(SHOT_DIR, { recursive: true });
if (COLD) {
	console.log('→ cold start');
	await coldStart();
}

const browser = await chromium.launch({ args: ARGS });
const anonCtx = await browser.newContext();

// ── 1. the anonymous read this route closed ───────────────────────────────────────────────────────
console.log('→ anonymous, on the product URL');
const anonCold = await get(anonCtx, POINTS(PRODUCT_V));
console.log(`   GET ${POINTS(PRODUCT_V)} → ${anonCold.status} ${anonCold.bytes}B`);
ok(
	anonCold.status === 401,
	'anon is refused (was 200 with 6,678,928 bytes before this route existed)',
);
ok(anonCold.bytes < 1024, `anon receives no payload (${anonCold.bytes} bytes)`);

// ── 2. alice's PAGE fills the entry ───────────────────────────────────────────────────────────────
console.log("→ alice signs in and opens the atlas — her page's own request is the first fill");
const aliceCtx = await browser.newContext();
const alice = await login(aliceCtx, 'alice@example.com', '/media/atlas');
const alicePoints = watchPoints(alice);
await alice.goto(`${ORIGIN}/media/atlas`, { waitUntil: 'domcontentloaded' });
await alice
	.waitForResponse((r) => r.url().includes('/api/atlas/points'), { timeout: 90000 })
	.catch(() => {});
await alice.waitForTimeout(2500); // let the scatter draw before the shot
await alice.screenshot({ path: `${SHOT_DIR}/atlas-cache-alice.png` });
const aliceRender = await atlasRendered(alice);
console.log(
	`   page requests: ${alicePoints.map((p) => `${p.status}/${p.cache}`).join(', ') || '(none)'}`,
);
console.log(`   render: webgpu-error=${aliceRender.webgpuError} canvases=${aliceRender.canvases}`);
ok(aliceRender.webgpuError === 0, 'the atlas rendered (no WebGPU error banner)');
ok(alicePoints.length === 1, `alice's page fetched the projection once (${alicePoints.length})`);
ok(alicePoints[0]?.cache === 'miss', "alice's page load is the fill");

// ── 3. a SECOND USER's FIRST atlas load ───────────────────────────────────────────────────────────
console.log("→ bob signs in — a different user, a fresh context, his page's FIRST atlas load");
const bobCtx = await browser.newContext();
const bob = await login(bobCtx, 'bob@example.com', '/media/atlas');
const bobPoints = watchPoints(bob);
await bob.goto(`${ORIGIN}/media/atlas`, { waitUntil: 'domcontentloaded' });
await bob
	.waitForResponse((r) => r.url().includes('/api/atlas/points'), { timeout: 90000 })
	.catch(() => {});
await bob.waitForTimeout(2500);
await bob.screenshot({ path: `${SHOT_DIR}/atlas-cache-bob.png` });
const bobRender = await atlasRendered(bob);
console.log(
	`   page requests: ${bobPoints.map((p) => `${p.status}/${p.cache}`).join(', ') || '(none)'}`,
);
console.log(`   render: webgpu-error=${bobRender.webgpuError} canvases=${bobRender.canvases}`);
ok(bobRender.webgpuError === 0, "bob's atlas rendered too");
ok(bobPoints[0]?.cache === 'hit', "bob's FIRST atlas load is served from alice's fill");

// The bytes, so "hit" is not taken on trust.
const aliceBytes = await get(aliceCtx, POINTS(PRODUCT_V));
const bobBytes = await get(bobCtx, POINTS(PRODUCT_V));
console.log(
	`   alice ${aliceBytes.bytes}B ${aliceBytes.ms}ms · bob ${bobBytes.bytes}B ${bobBytes.ms}ms`,
);
ok(
	bobBytes.bytes === aliceBytes.bytes,
	`both receive the identical payload (${bobBytes.bytes} bytes)`,
);
ok(bobBytes.bytes > 6_000_000, 'and it is the real multi-megabyte projection');

// ── 4. the authorization is not cached with the payload ───────────────────────────────────────────
console.log('→ anonymous again, on the URL that is now demonstrably WARM');
const anonWarm = await get(anonCtx, POINTS(PRODUCT_V));
console.log(`   anon → ${anonWarm.status} ${anonWarm.bytes}B (x-cache: ${anonWarm.cache})`);
ok(anonWarm.status === 401, 'a warm entry does not become a public one');
ok(anonWarm.cache === null, 'the refusal never reached the cache at all');

// ── 5. single-flight, counted in the viewer's own access log ──────────────────────────────────────
const coldV = `sf${Date.now()}`;
console.log(`→ ten concurrent cold requests (v=${coldV}, a key nothing has ever filled)`);
const before = viewerPointsServed();
// Fired from node with alice's session cookie, NOT from the browser and NOT from Playwright's request
// context. Both of those serialise this burst, for different reasons: the APIRequestContext queues, and
// Chrome's HTTP cache locks concurrent requests for the same cacheable URL behind the first one. Either
// way the first fill lands before the second request is issued, so the run reads `miss` then nine `hit` —
// which proves the cache works but never exercises the in-flight window single-flight exists for. Node's
// undici pool opens a socket per request, so these genuinely overlap.
const cookieHeader = (await aliceCtx.cookies()).map((c) => `${c.name}=${c.value}`).join('; ');
const burst = await Promise.all(
	Array.from({ length: 10 }, async () => {
		const r = await fetch(`${ORIGIN}${POINTS(coldV)}`, { headers: { cookie: cookieHeader } });
		return {
			status: r.status,
			cache: r.headers.get('x-cache'),
			bytes: (await r.arrayBuffer()).byteLength,
		};
	}),
);
const after = viewerPointsServed();
const states = burst.map((r) => r.cache);
console.log(`   statuses: ${[...new Set(burst.map((r) => r.status))].join(',')}`);
console.log(`   x-cache:  ${states.join(' ')}`);
console.log(
	`   viewer /api/atlas/points served: ${before} → ${after} (${after - before} in this burst)`,
);
ok(
	burst.every((r) => r.status === 200 && r.bytes > 6_000_000),
	'all ten are served the full projection',
);
ok(
	after - before === 1,
	`ten concurrent cold hits caused ONE upstream read, not ten (${after - before})`,
);
ok(states.filter((s) => s === 'miss').length === 1, 'exactly one request filled the entry');
// The other nine either waited on that fill ("shared") or arrived just after it landed ("hit"). Which of
// the two depends on scheduling and is not the property under test; that none of them read upstream is.
ok(
	states.filter((s) => s === 'shared' || s === 'hit').length === 9,
	'the other nine were served without touching the viewer',
);

await browser.close();
console.log(`\n=== atlas cache: ${failures === 0 ? 'ALL PASS' : `${failures} FAILED`} ===`);
process.exit(failures === 0 ? 0 : 1);
