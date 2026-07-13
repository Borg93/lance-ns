import { defineConfig, devices } from "@playwright/test";

// Frontend e2e for the lineage graph UI (GOAL 3 ③). Hermetic: the tests mock every `/api/**` response
// (the SvelteKit proxy → lineage service) via page.route, so no live backend is needed — CI-friendly.
// The dev server runs the real SSR + client hydration; the browser's /api calls are the only thing stubbed.
export default defineConfig({
	testDir: "./e2e",
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? "github" : "list",
	use: {
		// Port 5199 (not Vite's default 5173) — a shared dev box may already run another app there.
		baseURL: "http://localhost:5199",
		trace: "on-first-retry",
	},
	webServer: {
		command: "bun run dev --port 5199 --strictPort",
		port: 5199,
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
	projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
