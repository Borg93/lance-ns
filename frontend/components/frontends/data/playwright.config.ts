import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the data zone (namespaces · warehouses · tables · table-detail · access graph).
// Every `/capi/**` + `/api/**` response is mocked via page.route, so no live backend is needed — the
// dev server runs the real SSR + client hydration under this zone's `/data` base path, and the browser's
// backend calls are the only thing stubbed. Specs `goto` the base-prefixed routes (`/data/...`).
export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		// A dedicated e2e port (not the 5174 microfrontends dev port) so a running composition can't clash.
		baseURL: 'http://localhost:5294',
		trace: 'on-first-retry',
	},
	webServer: {
		command: 'bun run dev --port 5294 --strictPort',
		port: 5294,
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
