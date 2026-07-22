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
		// Run the admin zone AUTH-ON (the realistic governed state): OIDC configured → authEnabled=true, so
		// the shared nav-user renders the signed-out "Sign in" affordance (auth.spec.ts). Dummy issuer — the
		// specs assert the login LINK contract, never click through to a real Dex. The hermetic audit/dlq
		// specs mock their backend calls at the browser level, so they are unaffected by the auth state.
		env: {
			OIDC_ISSUER: 'http://dex.test/dex',
			OIDC_CLIENT_ID: 'lance-admin-e2e',
			OIDC_REDIRECT_URI: 'http://localhost:5295/auth/callback',
		},
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
