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
	projects: [
		// Warmup compiles the heavy routes ONCE before the parallel suite (same pattern as the data
		// zone): with fullyParallel on a big box a cold Vite cache makes the whole first wave starve
		// behind the initial compile and time out at 30s in a bundle — this suite was landing at ~27s
		// of a 30s budget purely on compile, so every added test moved it closer to the cliff.
		{ name: 'warmup', testMatch: /warmup\.setup\.ts/ },
		{ name: 'chromium', use: { ...devices['Desktop Chrome'] }, dependencies: ['warmup'] },
	],
});
