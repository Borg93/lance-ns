// P5 live proof: a REAL headless Dex login through the INGRESS origin, asserting the sealed session cookie
// carries ACROSS micro-frontend zones + per-user authz through the zones' BFF.
//
// The browser is 302'd to the issuer-derived authorize URL http://lance-ns-dex:5556/dex/auth — not
// resolvable from the host — so chromium launches with --host-resolver-rules mapping lance-ns-dex:5556 → the
// Dex port-forward. Each zone's BFF (in-cluster) does server-side discovery + confidential token-exchange via
// kube-dns, and tokens keep iss=http://lance-ns-dex:5556/dex so catalog/lineage accept the forwarded bearer.
//
// Prereq (see scripts/verify_cross_zone_oidc.sh): the zones deployed OIDC-on behind ingress-nginx, with the
// ingress controller + dex port-forwarded. Env: ORIGIN (the port-forwarded ingress origin).

import { chromium } from '@playwright/test';

const ORIGIN = process.env.ORIGIN ?? 'http://localhost:8090';
const ARGS = ['--host-resolver-rules=MAP lance-ns-dex:5556 127.0.0.1:5556'];

let failures = 0;
const ok = (cond, msg) => {
	console.log(`   ${cond ? '✓' : '✗ FAIL:'} ${msg}`);
	if (!cond) failures++;
};

/** The AppShell nav-user trigger button — its accessible name is the identity ("Sign in" when signed out,
 *  the user's name/email when signed in). One per page (the sidebar footer). */
const navUser = (page) => page.getByRole('button', { name: /Sign in|@|·/ }).last();

/** Drive a real Dex login for `user`, starting on the given zone path, and return the resulting page. The
 *  home zone owns /auth/login (origin-relative), so we navigate there directly (the nav-user's Sign in link
 *  points at exactly this) with a ?redirect back to the starting zone. */
async function login(context, user, startPath) {
	const page = await context.newPage();
	await page.goto(`${ORIGIN}/auth/login?redirect=${encodeURIComponent(startPath)}`, {
		waitUntil: 'domcontentloaded',
	});
	// Dex password form (skipApprovalScreen → straight to the form, then straight back to the callback).
	await page.waitForURL(/\/dex\/auth/, { timeout: 15000 });
	await page.fill('input[name="login"], input#login, input[type="text"], input[type="email"]', user);
	await page.fill('input[name="password"], input#password, input[type="password"]', 'password');
	await page.click('button[type="submit"], input[type="submit"], #submit-login');
	// Back on the starting zone off /auth — a real sealed session, not a seeded cookie.
	await page.waitForURL((u) => u.origin === ORIGIN && !u.pathname.startsWith('/auth'), {
		timeout: 20000,
	});
	if (page.url().includes('auth=error')) throw new Error(`login failed for ${user}: ${page.url()}`);
	return page;
}

const context = await (await chromium.launch({ args: ARGS })).newContext();

// 1. alice signs in on the DATA zone.
console.log('→ alice signs in on /data');
const alice = await login(context, 'alice', '/data');
ok(alice.url().startsWith(`${ORIGIN}/data`), `landed back on /data (${alice.url()})`);
const dataName = (await navUser(alice).textContent({ timeout: 8000 }))?.trim() ?? '';
ok(/alice/i.test(dataName), `nav-user shows the signed-in identity on /data (${dataName})`);

// 2. CROSS-ZONE: without re-authenticating, the SAME context lands signed-in on the ADMIN zone (one
//    origin, one path-"/" cookie). This is the crux of the migration.
console.log('→ same session on /admin (cross-zone cookie)');
const adminPage = await context.newPage();
await adminPage.goto(`${ORIGIN}/admin/audit`, { waitUntil: 'domcontentloaded' });
const adminName = (await navUser(adminPage).textContent({ timeout: 8000 }))?.trim() ?? '';
ok(!/^\s*Sign in/i.test(adminName) && /alice/i.test(adminName), `still signed in as alice on /admin (${adminName})`);
// alice is a produce-admin → the audit trail loads (a governed read, 2xx) rather than the 401/403 empty state.
await adminPage.waitForTimeout(1500);
const auditText = (await adminPage.locator('body').textContent())?.toLowerCase() ?? '';
ok(!auditText.includes('sign in to') && !auditText.includes('forbidden'), 'alice reads the governed /admin/audit surface');

// 3. bob signs in (fresh context) → denied on a produce-admin-gated surface (per-user authz, not a blanket).
console.log('→ bob is denied on the admin-gated surface');
const bobCtx = await (await chromium.launch({ args: ARGS })).newContext();
const bob = await login(bobCtx, 'bob', '/models/pipeline');
await bob.waitForTimeout(1000);
// bob triggers the cascade door on the pipeline page → the BFF forwards bob's bearer → lance-ray 403s him.
await bob.getByRole('button', { name: 'Run cascade' }).click().catch(() => {});
await bob.waitForTimeout(1500);
const bobText = (await bob.locator('body').textContent())?.toLowerCase() ?? '';
ok(bobText.includes('project-admin') || bobText.includes('403') || bobText.includes('denied'), 'bob is 403-denied on the produce door');

await context.close();
await bobCtx.close();
console.log(failures === 0 ? '\n✓ cross-zone OIDC + authz proven' : `\n✗ ${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
