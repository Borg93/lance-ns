import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the lineage zone (the medallion DAG explorer at the zone root `/lineage`). Every
// `/api/**` lineage response is mocked via page.route — no live lineage service needed. The dev server
// runs the real SSR + hydration under this zone's `/lineage` base path; the graph IS the zone root, so
// specs `goto('/lineage')`.
export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: 'http://localhost:5298',
		trace: 'on-first-retry',
	},
	webServer: {
		command: 'bun run dev --port 5298 --strictPort',
		port: 5298,
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
