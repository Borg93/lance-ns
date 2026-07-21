// Phase 3 live proof: a REAL headless Dex login (not a seeded cookie) + per-user authz through the BFF.
//
// The browser is 302'd to the issuer-derived authorize URL http://lance-ns-dex:5556/dex/auth — not
// resolvable from the host — so chromium launches with --host-resolver-rules mapping lance-ns-dex:5556 → the
// Dex port-forward. The web BFF (in-cluster) does server-side discovery + confidential token-exchange via
// kube-dns, and tokens keep iss=http://lance-ns-dex:5556/dex so catalog/lineage accept the forwarded bearer.
//
// Prereq (see scripts/verify_oidc_login.sh, which sets this up): web.oidc enabled on the release, and
// svc/<release>-web + svc/<release>-dex port-forwarded. Env: WEB_URL (the port-forwarded web origin).

import { chromium } from "@playwright/test";

const WEB = process.env.WEB_URL ?? "http://localhost:5280";
const ARGS = ["--host-resolver-rules=MAP lance-ns-dex:5556 127.0.0.1:5556"];

let failures = 0;
const ok = (cond, msg) => {
	console.log(`   ${cond ? "✓" : "✗ FAIL:"} ${msg}`);
	if (!cond) failures++;
};

/** Drive a real Dex login and return the signed-in display name from the authbar. */
async function login(context, user) {
	const page = await context.newPage();
	await page.goto(WEB, { waitUntil: "domcontentloaded" });
	// The Sign in affordance renders only when authEnabled (OIDC on) — its presence already proves the deploy.
	const signin = page.locator('a[href="/auth/login"]');
	await signin.waitFor({ state: "visible", timeout: 15000 });
	await signin.click();
	// Dex password form (skipApprovalScreen → straight to the form, then straight back to the callback).
	await page.waitForURL(/\/dex\/auth/, { timeout: 15000 });
	await page.fill('input[name="login"], input#login, input[type="text"], input[type="email"]', user);
	await page.fill('input[name="password"], input#password, input[type="password"]', "password");
	await page.click('button[type="submit"], input[type="submit"], #submit-login');
	// Back on the app off /auth — a real sealed session, not a seeded cookie.
	await page.waitForURL((u) => u.origin === new URL(WEB).origin && !u.pathname.startsWith("/auth"), { timeout: 20000 });
	if (page.url().includes("auth=error")) throw new Error(`login failed for ${user}: landed at ${page.url()}`);
	const who = (await page.locator(".authbar .who").first().textContent({ timeout: 8000 })) ?? "";
	return { page, who: who.trim() };
}

const browser = await chromium.launch({ args: ARGS });
try {
	console.log("\n── alice: real Dex login → sealed session → the admin door opens");
	const aliceCtx = await browser.newContext();
	const alice = await login(aliceCtx, "alice@example.com");
	ok(alice.who.length > 0, `alice signed in; authbar shows '${alice.who}' (real login, not a seeded cookie)`);
	const aProd = await alice.page.request.post(`${WEB}/medallion/produce`);
	ok(aProd.status() === 202, `alice POST /medallion/produce → ${aProd.status()} (want 202: produce-admin)`);
	await aliceCtx.close();

	console.log("\n── bob: real Dex login → denied the admin door (per-user authz, not just any authenticated)");
	const bobCtx = await browser.newContext();
	const bob = await login(bobCtx, "bob@example.com");
	ok(bob.who.length > 0, `bob signed in; authbar shows '${bob.who}'`);
	const bProd = await bob.page.request.post(`${WEB}/medallion/produce`);
	ok(bProd.status() === 403, `bob POST /medallion/produce → ${bProd.status()} (want 403: no can_administer)`);
	await bobCtx.close();
} finally {
	await browser.close();
}

console.log(
	failures === 0
		? "\n✅ PHASE 3 LIVE PROOF: real Dex browser login (AES-GCM sealed session), per-user authz through the BFF (alice 202 / bob 403)."
		: `\n✗ ${failures} check(s) failed`,
);
process.exit(failures === 0 ? 0 : 1);
