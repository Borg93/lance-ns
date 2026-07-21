import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the admin zone (audit · dlq). Every `/api/audit**` + `/api/admin/dlq**` response is
// mocked via page.route — no live catalog/lineage needed. The dev server runs the real SSR + hydration
// under this zone's `/admin` base path; specs `goto` the base-prefixed routes (`/admin/audit`, `/admin/dlq`).
export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: 'http://localhost:5295',
		trace: 'on-first-retry',
	},
	webServer: {
		command: 'bun run dev --port 5295 --strictPort',
		port: 5295,
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
