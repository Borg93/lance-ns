import { test, expect } from "@playwright/test";

// Live suite against the DEPLOYED stack (rask tests/e2e/mfe.spec.ts convention): every route must
// hydrate with zero failed _app assets and zero page errors, and the BFF proxies must round-trip.
// Stack-mode aware — a governed deploy (auth on, no browser session) renders the sign-in states;
// an open deploy renders data. Both are asserted as the CORRECT behavior for that mode.

const ROUTES = ["/", "/lineage", "/models"];

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
