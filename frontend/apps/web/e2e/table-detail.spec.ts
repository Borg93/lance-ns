import { test, expect, type Route } from "@playwright/test";

// Hermetic /tables/<id> coverage (#64/#66/#65): the detail page's catalog calls go through the /capi BFF,
// stubbed here — no live catalog needed (same pattern as models.spec.ts). Guards the version-management
// surface the wrong-image deploy proved was unguarded: the manifest-per-commit version table, the branches
// row, the tag-a-version form, and the two-click restore control.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const DETAIL = {
	describe: {
		version: 3,
		location: "s3://lance-catalog/db1$t",
		schema: { fields: [{ name: "id", type: "int64", nullable: false }] },
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
	branches: { branches: { main: { createAt: 1_700_000_000, manifestSize: 512 } } },
	indexes: { indexes: [{ index_name: "id_idx", columns: ["id"], index_type: "BTREE" }] },
	policy: { retention_days: 7, retain_versions: 5, compact_enabled: true },
};

// The writes the interaction tests make; recorded so we can assert the BFF POST fired with the right body.
let tagPost: { tag: string; version: number } | null;
let restorePost: { version: number } | null;

test.beforeEach(async ({ page }) => {
	tagPost = null;
	restorePost = null;
	await page.route("**/capi/**", (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^\/capi/, "");
		if (path.endsWith("/detail")) return json(route, DETAIL);
		if (path.endsWith("/tags") && req.method() === "POST") {
			tagPost = req.postDataJSON() as { tag: string; version: number };
			return json(route, { tag: tagPost.tag, version: tagPost.version });
		}
		if (path.endsWith("/restore") && req.method() === "POST") {
			restorePost = req.postDataJSON() as { version: number };
			return json(route, { version: 4 });
		}
		return json(route, { detail: "unstubbed" }, 404);
	});
});

test("renders the manifest-per-commit version table, branches, and tags (#66)", async ({
	page,
}) => {
	await page.goto("/tables/db1%24t");
	await expect(page.getByRole("heading", { name: "db1$t" })).toBeVisible();
	const section = page.locator("section", { hasText: "Versions, branches & tags" });
	// newest-first version rows with the manifest size surfaced
	await expect(section.locator("tbody tr").first()).toContainText("v3");
	await expect(section.locator("tbody tr").first()).toContainText("2.0 KiB");
	await expect(section).toContainText("v1");
	// branches row + the tag chip
	await expect(section).toContainText("main");
	await expect(section).toContainText("blessed → v2");
	// indexes section (#64)
	const indexes = page.locator("section", { hasText: "Indexes" });
	await expect(indexes).toContainText("id_idx");
	await expect(indexes).toContainText("BTREE");
});

test("tag-a-version form posts {tag, version} through the BFF (#64)", async ({ page }) => {
	await page.goto("/tables/db1%24t");
	const section = page.locator("section", { hasText: "Versions, branches & tags" });
	await section.getByPlaceholder("tag name (e.g. blessed)").fill("release-1");
	await section.locator(".tagform select").selectOption("3");
	await section.getByRole("button", { name: "Tag version" }).click();
	await expect.poll(() => tagPost).toEqual({ tag: "release-1", version: 3 });
});

test("restore is a two-click confirm and posts {version} (#64)", async ({ page }) => {
	await page.goto("/tables/db1%24t");
	const section = page.locator("section", { hasText: "Versions, branches & tags" });
	const firstRow = section.locator("tbody tr").first(); // v3
	await firstRow.getByRole("button", { name: "restore" }).click();
	// first click only arms the confirm — no write yet
	expect(restorePost).toBeNull();
	await firstRow.getByRole("button", { name: "confirm restore" }).click();
	await expect.poll(() => restorePost).toEqual({ version: 3 });
});
