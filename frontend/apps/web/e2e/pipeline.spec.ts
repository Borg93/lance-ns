import { test, expect, type Route } from "@playwright/test";

// Hermetic /pipeline coverage (#64): the human trigger door fires the cascade (/medallion/produce) and a
// training run (/medallion/train). Mock the two BFF calls; assert the success banners carry the run token
// and that a 403 renders the project-admin denial (not a silent no-op). This is a pure ACTION page (no
// initial data fetch), so wait for networkidle to let the client module load + hydrate before clicking —
// otherwise the first click can land on a not-yet-hydrated button (no onclick attached).

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

test("Run cascade fires produce and shows the run token", async ({ page }) => {
	let method = "";
	await page.route("**/medallion/produce", (route) => {
		method = route.request().method();
		return json(route, { status: "published", token: "run-abc" }, 202);
	});
	await page.goto("/pipeline");
	await page.waitForLoadState("networkidle");
	await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
	await page.getByRole("button", { name: "Run cascade" }).click();
	await expect(page.locator(".banner.ok")).toContainText("run-abc");
	expect(method).toBe("POST");
});

test("Request training posts the model + parsed feature datasets", async ({ page }) => {
	let seenBody: { model?: string; features?: { dataset: string }[] } = {};
	await page.route("**/medallion/train", async (route) => {
		seenBody = JSON.parse(route.request().postData() ?? "{}");
		return json(route, { status: "published", token: "train-1", model: "churn" }, 202);
	});
	await page.goto("/pipeline");
	await page.waitForLoadState("networkidle");
	await page.getByLabel("Model name").fill("churn");
	await page.getByLabel("Feature datasets").fill("silver$a, silver$b");
	await page.getByRole("button", { name: "Request training" }).click();
	await expect(page.locator(".banner.ok")).toContainText("train-1");
	expect(seenBody.model).toBe("churn");
	expect(seenBody.features).toEqual([{ dataset: "silver$a" }, { dataset: "silver$b" }]);
});

test("a 403 renders the project-admin denial banner", async ({ page }) => {
	await page.route("**/medallion/produce", (route) =>
		json(route, { detail: "produce needs project admin" }, 403),
	);
	await page.goto("/pipeline");
	await page.waitForLoadState("networkidle");
	await page.getByRole("button", { name: "Run cascade" }).click();
	await expect(page.locator(".banner.fail")).toContainText("project-admin rung");
});

test("nav exposes the Pipeline route", async ({ page }) => {
	await page.goto("/pipeline");
	await expect(page.locator(".navbar a.active")).toHaveText("Pipeline");
});
