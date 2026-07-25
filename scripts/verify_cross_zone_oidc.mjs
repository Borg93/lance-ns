// P5 live proof: a REAL headless Dex login through the INGRESS origin, asserting the sealed session cookie
// carries ACROSS micro-frontend zones + per-user authz through the zones' BFF.
//
// The browser is 302'd to the issuer-derived authorize URL http://lance-ns-dex:5556/dex/auth — not
// resolvable from the host — so chromium launches with --host-resolver-rules mapping lance-ns-dex:5556 → the
// Dex port-forward. Each zone's BFF (in-cluster) does server-side discovery + confidential token-exchange via
// kube-dns, and tokens keep iss=http://lance-ns-dex:5556/dex so catalog/lineage/lance-ray accept the bearer.
//
// Prereq (set up by scripts/verify_cross_zone_oidc.sh): the zones deployed OIDC-on behind ingress-nginx,
// alice granted admin on project:acme in OpenFGA, the ingress + Dex port-forwarded. Env: ORIGIN.

import { chromium } from '@playwright/test';

const ORIGIN = process.env.ORIGIN ?? 'http://localhost:8090';
const ARGS = ['--host-resolver-rules=MAP lance-ns-dex:5556 127.0.0.1:5556'];

let failures = 0;
const ok = (cond, msg) => {
	console.log(`   ${cond ? '✓' : '✗ FAIL:'} ${msg}`);
	if (!cond) failures++;
};

/** The AppShell nav-user trigger button — its accessible name is the identity ("Sign in" when signed out,
 *  the user's name/email when signed in). The sidebar footer button. */
const navUserText = async (page) => {
	const btn = page.getByRole('button', { name: /Sign in|@|alice|bob/i }).last();
	return ((await btn.textContent({ timeout: 10000 })) ?? '').replace(/\s+/g, ' ').trim();
};

/** Drive a real Dex login for `user`, starting on `startPath`. The home zone owns /auth/login
 *  (origin-relative); we navigate there with a ?redirect back to the starting zone. */
async function login(context, user, startPath) {
	const page = await context.newPage();
	await page.goto(`${ORIGIN}/auth/login?redirect=${encodeURIComponent(startPath)}`, {
		waitUntil: 'domcontentloaded',
	});
	await page.waitForURL(/\/dex\/auth/, { timeout: 15000 });
	await page.fill('input[name="login"], input#login, input[type="text"], input[type="email"]', user);
	await page.fill('input[name="password"], input#password, input[type="password"]', 'password');
	await page.click('button[type="submit"], input[type="submit"], #submit-login');
	await page.waitForURL((u) => u.origin === ORIGIN && !u.pathname.startsWith('/auth'), {
		timeout: 20000,
	});
	if (page.url().includes('auth=error')) throw new Error(`login failed for ${user}: ${page.url()}`);
	return page;
}

// 1. alice signs in on the DATA zone.
console.log('→ alice signs in on /lakehouse/data');
const aliceCtx = await (await chromium.launch({ args: ARGS })).newContext();
const alice = await login(aliceCtx, 'alice@example.com', '/lakehouse/data');
ok(
	alice.url().startsWith(`${ORIGIN}/lakehouse/data`),
	`landed back on /lakehouse/data (${alice.url()})`,
);
ok(/alice/i.test(await navUserText(alice)), 'nav-user shows alice on /lakehouse/data');

// 2. CROSS-ZONE: the SAME context lands signed-in on the MEDIA zone (one origin, one path-"/" cookie) —
//    the crux of the migration. No re-auth.
//    Media, NOT /lakehouse/admin: the catalog, lineage, models and admin areas merged into the one
//    lakehouse zone, so a hop between them is a soft navigation inside a single app and proves nothing
//    about a cookie crossing a zone. This step has to target a genuinely separate deployment or it
//    silently stops testing what it exists for.
console.log('→ same session on /media (cross-zone cookie)');
const aliceMedia = await aliceCtx.newPage();
await aliceMedia.goto(`${ORIGIN}/media`, { waitUntil: 'domcontentloaded' });
ok(/alice/i.test(await navUserText(aliceMedia)), 'still signed in as alice on /media — cross-zone cookie');

// 3. alice (project-admin) opens the governed produce door via the lakehouse BFF (her bearer is
//    forwarded → lance-ray authorizes) → 2xx success banner.
console.log('→ alice runs the cascade (governed 2xx)');
const alicePipe = await aliceCtx.newPage();
await alicePipe.goto(`${ORIGIN}/lakehouse/models/pipeline`, { waitUntil: 'domcontentloaded' });
await alicePipe.waitForLoadState('networkidle');
await alicePipe.getByRole('button', { name: 'Run cascade' }).click();
await alicePipe.waitForTimeout(2500);
const aliceBanner = ((await alicePipe.locator('.banner').first().textContent().catch(() => '')) ?? '').trim();
ok(/run|published|token|ok/i.test(aliceBanner) && !/project-admin|denied|403/i.test(aliceBanner),
	`alice's cascade opened the door (banner: ${aliceBanner || '(none)'})`);

// 4. bob (no grant, fresh context) is DENIED on the same door → 403 project-admin banner (per-user authz,
//    not a blanket allow).
console.log('→ bob is denied on the same door (403)');
const bobCtx = await (await chromium.launch({ args: ARGS })).newContext();
const bobPipe = await login(bobCtx, 'bob@example.com', '/lakehouse/models/pipeline');
await bobPipe.waitForLoadState('networkidle');
await bobPipe.getByRole('button', { name: 'Run cascade' }).click();
await bobPipe.waitForTimeout(2500);
const bobBanner = ((await bobPipe.locator('.banner').first().textContent().catch(() => '')) ?? '').trim();
ok(/project-admin|denied|403|forbidden/i.test(bobBanner), `bob is 403-denied (banner: ${bobBanner || '(none)'})`);

await aliceCtx.close();
await bobCtx.close();
console.log(failures === 0 ? '\n✓ cross-zone OIDC + per-user authz PROVEN' : `\n✗ ${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
