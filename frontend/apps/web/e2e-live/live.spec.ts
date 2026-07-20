import { test, expect } from "@playwright/test";

// Live suite against the DEPLOYED stack (rask tests/e2e/mfe.spec.ts convention): every route must
// hydrate with zero failed _app assets and zero page errors, and the BFF proxies must round-trip.
// Stack-mode aware — a governed deploy (auth on, no browser session) renders the sign-in states;
// an open deploy renders data. Both are asserted as the CORRECT behavior for that mode.

const ROUTES = ["/", "/lineage", "/models", "/tables", "/warehouses", "/experiments"];

for (const route of ROUTES) {
	test(`hydrates: ${route}`, async ({ page }) => {
		const appAsset404: string[] = [];
		const pageErrors: string[] = [];
		page.on("requestfailed", (r) => {
			if (r.url().includes("/_app/")) appAsset404.push(r.url());
		});
		page.on("response", (r) => {
			if (r.url().includes("/_app/") && r.status() >= 400) appAsset404.push(r.url());
		});
		page.on("pageerror", (e) => pageErrors.push(String(e)));
		const resp = await page.goto(route, { waitUntil: "networkidle" });
		expect(resp?.status(), `status for ${route}`).toBe(200);
		await page.waitForTimeout(800);
		expect(appAsset404, `failed _app assets on ${route}`).toEqual([]);
		expect(pageErrors, `page errors on ${route}`).toEqual([]);
	});
}

test("nav renders on every page and routes between lineage and models", async ({ page }) => {
	await page.goto("/models", { waitUntil: "networkidle" });
	await expect(page.locator(".navbar a.active")).toHaveText("Models");
	await page.locator(".navbar a", { hasText: "Lineage" }).click();
	await expect(page).toHaveURL(/\/$/);
});

test("lineage BFF round-trips: /api/datasets answers 2xx JSON (service door on a governed stack)", async ({
	request,
}) => {
	const res = await request.get("/api/datasets", { maxRedirects: 0 });
	expect(
		res.status(),
		"/api/datasets should be served (user session OR service door)",
	).toBeLessThan(300);
	const body = (await res.json()) as { datasets?: unknown[] };
	expect(Array.isArray(body.datasets), "datasets list shape").toBe(true);
});

test("catalog BFF round-trips: /capi/v1/model answers per stack mode; /capi never exposes /docs", async ({
	request,
}) => {
	const models = await request.get("/capi/v1/model", { maxRedirects: 0 });
	// Governed stack without a browser session → the catalog's own 401 passes through as JSON;
	// open stack → 200 with the models list. Anything else (5xx, HTML error page) is a real break.
	expect([200, 401], `unexpected /capi/v1/model status ${models.status()}`).toContain(
		models.status(),
	);
	const body = (await models.json()) as Record<string, unknown>;
	if (models.status() === 200) {
		expect(Array.isArray(body.models), "models list shape").toBe(true);
	} else {
		expect(typeof body.detail === "string" || typeof body.error === "string").toBe(true);
	}
	const docs = await request.get("/capi/docs", { maxRedirects: 0 });
	expect(docs.status(), "the catalog's open /docs surface must not leak through the BFF").toBe(404);
});

test("models page renders the correct state for the stack mode (sign-in vs data)", async ({
	page,
	request,
}) => {
	const probe = await request.get("/capi/v1/model");
	await page.goto("/models", { waitUntil: "networkidle" });
	await expect(page.getByRole("heading", { name: "Model registry" })).toBeVisible();
	if (probe.status() === 401) {
		await expect(page.locator(".empty")).toContainText("sign in");
	} else {
		// Open stack: either real rows or the honest empty state — never the offline banner.
		await expect(page.locator(".empty, table tbody tr").first()).toBeVisible();
		await expect(page.locator(".empty")).not.toContainText("unreachable");
	}
});

test("governance writes through the BFF are session-gated per stack mode (#49 confused-deputy leg)", async ({
	request,
}) => {
	// Anonymous PUT via the web BFF: a governed stack must answer 401 (either the BFF's own short-circuit
	// when OIDC is configured, or the lineage writer gate's) — never a write executed under any service
	// credential. An open stack answers 200/404 from the open lineage service (404 = unknown dataset).
	const probe = await request.get("/capi/v1/model");
	const res = await request.put("/api/datasets/no-such-dataset/tags/e2e-live-probe", {
		maxRedirects: 0,
	});
	if (probe.status() === 401) {
		expect(res.status(), "governed stack: anonymous governance write must be 401").toBe(401);
	} else {
		expect([200, 404], `open stack: got ${res.status()}`).toContain(res.status());
	}
});

test("access review through the BFF is session-gated per stack mode (#51 confused-deputy leg)", async ({
	request,
}) => {
	// Anonymous POST via the narrow access route: a governed stack must answer 401 (the BFF's own
	// short-circuit, or the catalog's) — an ACL enumeration must never run under any service credential.
	// An open (auth-off) stack answers the catalog's honest 501 ("no grants to review without FGA").
	const probe = await request.get("/capi/v1/model");
	const res = await request.post("/capi/v1/table/no-such-table/access/list", { maxRedirects: 0 });
	if (probe.status() === 401) {
		expect(res.status(), "governed stack: anonymous access review must be 401").toBe(401);
	} else {
		expect(res.status(), "open stack: access review answers the catalog's 501").toBe(501);
	}
	// The generic /capi catch-all stays GET-only — the narrow route must be the only POST door.
	const other = await request.post("/capi/v1/table/no-such-table/describe", { maxRedirects: 0 });
	expect([404, 405], `generic /capi POST must stay closed, got ${other.status()}`).toContain(
		other.status(),
	);
});

test("tables + warehouses pages render the correct state for the stack mode (#52)", async ({
	page,
	request,
}) => {
	// Governed without a browser session ⇒ both pages render their sign-in state; open stack ⇒ data
	// or the honest empty state. Either is the CORRECT render for the mode — a crash or the offline
	// banner fails both ways.
	const probe = await request.get("/capi/v1/model");
	await page.goto("/tables", { waitUntil: "networkidle" });
	await expect(page.getByRole("heading", { name: "Tables" })).toBeVisible();
	if (probe.status() === 401) {
		await expect(page.locator(".empty")).toContainText("sign in");
	} else {
		await expect(page.locator(".empty, .list li").first()).toBeVisible();
		await expect(page.locator(".empty")).not.toContainText("unreachable");
	}
	await page.goto("/warehouses", { waitUntil: "networkidle" });
	await expect(page.getByRole("heading", { name: "Warehouses" })).toBeVisible();
	if (probe.status() === 401) {
		await expect(page.locator(".empty")).toContainText("sign in");
	}
});

test("table-detail page renders per stack mode; policy + warehouse writes are session-gated (#52 confused-deputy legs)", async ({
	page,
	request,
}) => {
	const probe = await request.get("/capi/v1/model");
	await page.goto("/tables/no-such%24table", { waitUntil: "networkidle" });
	if (probe.status() === 401) {
		await expect(page.locator(".empty")).toContainText("sign in");
	} else {
		// Open stack: an unknown table renders the honest not-in-catalog state.
		await expect(page.locator(".empty")).toContainText("Not a catalog-registered table");
	}
	// Anonymous writes through the narrow BFF routes: governed ⇒ 401 without leaving the BFF; open ⇒
	// the catalog's own answer. Both probes are side-effect-free — the policy write targets a missing
	// table (404/422), and the warehouse create sends a deliberately invalid body (missing project →
	// 422) so an open stack is never actually mutated by the test.
	const policy = await request.put("/capi/v1/table/no-such%24table/policy", {
		maxRedirects: 0,
		headers: { "content-type": "application/json" },
		data: { retention_days: 1 },
	});
	const wh = await request.post("/capi/v1/warehouses", {
		maxRedirects: 0,
		headers: { "content-type": "application/json" },
		data: { bucket: "no-id-no-project" }, // invalid: id + project are required → 422, no provisioning
	});
	if (probe.status() === 401) {
		expect(policy.status(), "governed: anonymous policy write must be 401").toBe(401);
		expect(wh.status(), "governed: anonymous warehouse create must be 401").toBe(401);
	} else {
		expect([404, 422], `open: policy write got ${policy.status()}`).toContain(policy.status());
		expect(wh.status(), "open: invalid warehouse create is rejected, not provisioned").toBe(422);
	}
	// The warehouse action route's allowlist: an unknown action is a 404, never a forwarded call.
	const bad = await request.post("/capi/v1/warehouses/x/drop-everything", { maxRedirects: 0 });
	expect(bad.status()).toBe(404);
});

test("the session-only version-mgmt + access-check BFF routes are LIVE and session-gated (#64/#68)", async ({
	request,
}) => {
	// Each is a narrow session-only POST route added this session (tag a version / restore a version /
	// simulate an access check). Two properties per route: (1) it must EXIST — a 405 means the request fell
	// through to the GET-only /capi catch-all, i.e. the route regressed or a stale build shipped (this is
	// exactly the stale-deploy signature a request-level render check catches); (2) on a governed stack an
	// anonymous caller is refused with 401 without the request leaving the BFF (the confused-deputy stance).
	const probe = await request.get("/capi/v1/model");
	const governed = probe.status() === 401;
	const routes = [
		{ path: "/capi/v1/table/no-such%24t/tags", data: { tag: "e2e-live-probe", version: 1 } },
		{ path: "/capi/v1/table/no-such%24t/restore", data: { version: 1 } },
		{
			path: "/capi/v1/table/no-such%24t/access/check",
			data: { user: "alice", relation: "can_read_data" },
		},
	];
	for (const r of routes) {
		const res = await request.post(r.path, {
			maxRedirects: 0,
			headers: { "content-type": "application/json" },
			data: r.data,
		});
		expect(
			res.status(),
			`${r.path} regressed to the GET-only catch-all (405 = stale/missing route)`,
		).not.toBe(405);
		if (governed) {
			expect(res.status(), `governed: anonymous ${r.path} must be 401`).toBe(401);
		}
	}
});

test("experiments page renders the embedded training dashboard from real metrics (#53)", async ({
	page,
	request,
}) => {
	// The /api/experiments BFF runs the deployed Perses "Model Training" dashboard's PromQL queries
	// against GreptimeDB server-side. On a stack with observability it returns the panels; without it,
	// a 501. Either way the page renders its correct state — never a crash or a leaked credential.
	const probe = await request.get("/api/experiments", { maxRedirects: 0 });
	expect([200, 501, 502], `unexpected /api/experiments status ${probe.status()}`).toContain(
		probe.status(),
	);
	if (probe.status() === 200) {
		const body = (await probe.json()) as { panels?: { title?: string }[]; source?: string };
		expect(Array.isArray(body.panels), "dashboard panels shape").toBe(true);
		expect(body.source, "metrics sourced from GreptimeDB").toContain("GreptimeDB");
	}
	await page.goto("/experiments", { waitUntil: "networkidle" });
	await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
	// The page never exposes a raw credential or a stack trace to the browser.
	await expect(page.locator(".page")).not.toContainText("password");
});

test("browse search uses the server-side FGA-filtered /search (#52)", async ({ request }) => {
	// The BFF /api/search round-trips (service door on governed stacks — same posture as /api/datasets).
	const res = await request.get("/api/search?q=gold", { maxRedirects: 0 });
	expect(res.status(), "/api/search should answer").toBeLessThan(300);
	const body = (await res.json()) as { results?: unknown[] };
	expect(Array.isArray(body.results), "search results shape").toBe(true);
});

test("grants panel renders the correct access-review state for the stack mode (#51)", async ({
	page,
	request,
}) => {
	// Select a dataset from the browse list (served via the lineage service door even anonymously),
	// open its details, expand the access review — a governed stack without a browser session renders
	// the sign-in state; an auth-off stack renders the honest no-grants message. Both are the CORRECT
	// render for the mode; a broken panel (crash, offline text, raw error) fails either way.
	const probe = await request.get("/capi/v1/model");
	await page.goto("/", { waitUntil: "networkidle" });
	const firstRow = page.locator(".browse-row").first();
	await expect(firstRow, "browse list should have datasets on the deployed stack").toBeVisible();
	await firstRow.click();
	await page.locator(".tab", { hasText: "Details" }).click();
	const head = page.locator(".grants .head");
	await expect(head, "the access-review toggle renders in the details panel").toBeVisible();
	await head.click();
	const state = page.locator(".grants .mut, .grants .acl").first();
	await expect(state).toBeVisible();
	if (probe.status() === 401) {
		await expect(page.locator(".grants")).toContainText("Sign in to review access.");
	} else {
		// Open stack: the catalog's 501 message, a denial, or a real ACL table — never a crash.
		await expect(page.locator(".grants")).not.toContainText("undefined");
	}
});
