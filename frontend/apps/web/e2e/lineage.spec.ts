import { test, expect, type Route } from "@playwright/test";

// The medallion DAG the mocked lineage API returns. GraphEdge semantics: `source` is derived_from
// `target` (output → input), matching services/lineage/schemas.py.
const NODES = [
	{ id: "raw_events", namespace: "raw", source_uri: "s3://lakehouse/raw_events", tags: [] },
	{
		id: "bronze$events",
		namespace: "bronze",
		source_uri: "s3://lakehouse/bronze",
		tags: ["layer=bronze"],
	},
	{
		id: "silver$features",
		namespace: "silver",
		source_uri: "s3://lakehouse/silver",
		tags: ["layer=silver"],
	},
	{
		id: "gold$catalog",
		namespace: "gold",
		source_uri: "s3://lakehouse/gold",
		tags: ["layer=gold"],
	},
];
const EDGES = [
	{ source: "bronze$events", target: "raw_events", kind: "derived_from" },
	{ source: "silver$features", target: "bronze$events", kind: "derived_from" },
	{ source: "gold$catalog", target: "silver$features", kind: "derived_from" },
];

const json = (route: Route, body: unknown) =>
	route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

// Stub every lineage-API call the UI makes through the SvelteKit proxy — no live backend needed.
test.beforeEach(async ({ page }) => {
	await page.route("**/api/**", (route) => {
		const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
		const m = path.match(/^\/datasets\/([^/]+)\/(producers|graph|columns)/);
		if (m) {
			const id = decodeURIComponent(m[1]);
			if (m[2] === "producers")
				return json(route, {
					dataset: id,
					producers: [
						{
							run_id: `run-${id}`,
							author: "alice",
							event_type: "COMPLETE",
							dataset_version: "1",
							event_time: "2026-07-01T00:00:00Z",
						},
					],
				});
			if (m[2] === "graph") return json(route, { root: id, nodes: NODES, edges: EDGES });
			return json(route, { root: id, columns: [], edges: [] }); // columns
		}
		if (path === "/datasets")
			return json(route, {
				datasets: NODES.map((n) => ({ name: n.id, namespace: n.namespace, tags: n.tags })),
				total: NODES.length,
			});
		if (path === "/events") return json(route, { events: [] });
		if (path === "/runs")
			return json(route, {
				runs: [
					{
						run_id: "r-1",
						job: "ray-jobs/embed_features",
						state: "RUNNING",
						progress_done: 1,
						progress_total: 3,
						author: "alice",
						outputs: ["silver$features"],
						updated_at: "2026-07-01T00:00:00Z",
						events: 2,
					},
					{
						run_id: "r-2",
						job: "ray-jobs/promote_gold",
						state: "FAIL",
						author: "bob",
						error_message: "quality gate: row_count below floor",
						updated_at: "2026-07-01T00:01:00Z",
						events: 3,
					},
				],
			});
		if (path === "/jobs")
			return json(route, {
				jobs: [
					{ namespace: "lance-medallion", name: "embed_features", outputs: ["silver$features"] },
				],
				total: 1,
			});
		if (path === "/namespaces")
			return json(route, { namespaces: ["bronze", "gold", "raw", "silver"] });
		if (path.startsWith("/search"))
			return json(route, {
				query: "embed",
				results: [
					{ name: "silver$features", namespace: "silver", tags: [], matches: ["column:embedding"] },
				],
				total: 1,
			});
		if (path === "/demo/datasets") return json(route, { datasets: [] });
		return json(route, {});
	});
});

test("renders the medallion DAG at /lineage", async ({ page }) => {
	await page.goto("/lineage");
	// SvelteFlow wraps each custom node in .svelte-flow__node — the 4 medallion datasets.
	const nodes = page.locator(".svelte-flow__node");
	await expect(nodes).toHaveCount(4, { timeout: 15_000 });
	// Scope to graph nodes — the browse-panel list also renders these names (the node's URI div also
	// contains the name, so filter by the node, not exact text).
	await expect(nodes.filter({ hasText: "raw_events" })).toBeVisible();
	await expect(nodes.filter({ hasText: "gold$catalog" })).toBeVisible();
});

test("clicking a dataset node shows its upstream + downstream in the detail panel", async ({
	page,
}) => {
	await page.goto("/lineage");
	await expect(page.locator(".svelte-flow__node")).toHaveCount(4, { timeout: 15_000 });

	// Click the silver node — it has both an upstream (bronze) and a downstream (gold).
	await page.locator(".svelte-flow__node").filter({ hasText: "silver$features" }).click();
	await page.getByRole("tab", { name: "Details" }).click();

	await expect(page.getByRole("heading", { name: "silver$features" })).toBeVisible();
	await expect(page.getByText("Upstream")).toBeVisible();
	await expect(page.getByRole("button", { name: "bronze$events" })).toBeVisible();
	await expect(page.getByText("Downstream")).toBeVisible();
	await expect(page.getByRole("button", { name: "gold$catalog" })).toBeVisible();

	// The upstream chip reselects that dataset — the panel follows.
	await page.getByRole("button", { name: "bronze$events" }).click();
	await expect(page.getByRole("heading", { name: "bronze$events" })).toBeVisible();
});

test("browse landing lists datasets from /datasets, filters, and focuses on click", async ({
	page,
}) => {
	await page.goto("/lineage");
	// Browse is the default aside tab — the governed /datasets catalog renders as a filterable list, so a
	// visitor can start with no dataset name in hand (GOAL 4 A3).
	const rows = page.locator(".browse-row");
	await expect(rows).toHaveCount(4, { timeout: 15_000 });
	await expect(page.locator(".browse-name", { hasText: "raw_events" })).toBeVisible();

	// Filtering narrows the list to matches (by name / namespace / tag).
	await page.getByLabel("Filter datasets").fill("silver");
	await expect(rows).toHaveCount(1);
	await expect(page.locator(".browse-name")).toHaveText("silver$features");

	// Clicking a dataset focuses it — the row is marked selected and Details reflects it.
	await rows.first().click();
	await expect(page.locator(".browse-row.on")).toHaveCount(1);
	await page.getByRole("tab", { name: "Details" }).click();
	await expect(page.getByRole("heading", { name: "silver$features" })).toBeVisible();
});

test("governed search finds by column and focuses the hit; jobs tab lists compute identities", async ({
	page,
}) => {
	// ASSERTS (Batch 12): the SearchBar (packages/ui) drives the governed /search endpoint — a
	// column-tier hit renders its WHY-chip (column:embedding) and selecting it focuses the dataset;
	// the new Jobs tab lists the governed compute identities with clickable outputs.
	await page.goto("/lineage");
	await page.getByLabel("search").fill("embed");
	const hit = page.getByRole("listbox").getByRole("button");
	await expect(hit).toContainText("silver$features");
	await expect(hit).toContainText("column:embedding"); // the match-reason chip
	await hit.click();
	await page.getByRole("tab", { name: "Details" }).click();
	await expect(page.getByRole("heading", { name: "silver$features" })).toBeVisible();

	await page.getByRole("tab", { name: "Jobs (1)" }).click();
	// Scope to the jobs list's own class — the status board's run row ALSO contains this job name
	// and bits-ui keeps inactive tab content in the DOM (the Batch 12 collision lesson).
	await expect(page.locator(".job-name", { hasText: "embed_features" })).toBeVisible();
});

test("status board renders live runs from the workspace lib (@lance/ui StatusBoard)", async ({
	page,
}) => {
	// ASSERTS (Batch 14): the EXTRACTED StatusBoard renders real rows under the host app — the
	// Batch 12 lesson was that a workspace-lib component can compile clean yet break only at
	// render/interaction time, so the extraction is pinned by rendered output, not just svelte-check.
	// One RUNNING row (progress label from progress_done/total) + one FAIL row (error strip).
	await page.goto("/lineage");
	await page.getByRole("tab", { name: "Status (2)" }).click();
	await expect(page.getByText("embed_features", { exact: false }).first()).toBeVisible();
	await expect(page.getByText("RUNNING 1/3")).toBeVisible();
	await expect(page.getByText("FAIL", { exact: true })).toBeVisible();
	await expect(page.getByText("quality gate: row_count below floor")).toBeVisible();
	await expect(page.getByText("→ silver$features")).toBeVisible();
});
