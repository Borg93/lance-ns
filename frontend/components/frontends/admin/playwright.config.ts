import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the admin zone (audit · dlq · control-events). The audit/dlq specs mock `/api/**` via
// page.route; the control-events feed is a `query.live` remote function that polls the catalog SERVER-SIDE
// (unreachable by page.route), so a second webServer runs an in-memory mock catalog (e2e/mock-catalog.ts)
// and the dev server's CATALOG_API points at it. The dev server runs the real SSR + hydration under this
// zone's `/admin` base path; specs `goto` the base-prefixed routes (`/admin/audit`, `/admin/events`, …).
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
	webServer: [
		{
			command: 'bun run dev --port 5295 --strictPort',
			port: 5295,
			reuseExistingServer: !process.env.CI,
			timeout: 120_000,
			// Run the admin zone AUTH-ON (the realistic governed state): OIDC configured → authEnabled=true, so
			// the shared nav-user renders the signed-out "Sign in" affordance (auth.spec.ts). Dummy issuer — the
			// specs assert the login LINK contract, never click through to a real Dex. The hermetic audit/dlq
			// specs mock their backend calls at the browser level, so they are unaffected by the auth state.
			env: {
				OIDC_ISSUER: 'http://dex.test/dex',
				OIDC_CLIENT_ID: 'lance-admin-e2e',
				OIDC_REDIRECT_URI: 'http://localhost:5295/auth/callback',
				// The control-events feed's query.live generator polls this server-side — the mock catalog below.
				// 5297, NOT 5296: the zone e2e ports are home 5293 / data 5294 / admin 5295 / models 5296 /
				// lineage 5298, and a locally parallel `turbo run test:e2e` (reuseExistingServer) would silently
				// "reuse" the models dev server as the catalog (audit finding).
				CATALOG_API: 'http://localhost:5297',
			},
		},
		{
			command: 'bun e2e/mock-catalog.ts',
			port: 5297,
			reuseExistingServer: !process.env.CI,
			timeout: 30_000,
		},
	],
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
