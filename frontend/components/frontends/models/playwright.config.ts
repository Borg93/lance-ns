import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the models zone (registry · experiments · pipeline). Every `/capi/**` + `/api/**` +
// `/medallion/**` response is mocked via page.route — no live catalog/GreptimeDB needed. The dev server
// runs the real SSR + hydration under this zone's `/models` base path; specs `goto` the base-prefixed
// routes (`/models`, `/models/experiments`, `/models/pipeline`).
export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: 'http://localhost:5296',
		trace: 'on-first-retry',
	},
	webServer: {
		command: 'bun run dev --port 5296 --strictPort',
		port: 5296,
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
