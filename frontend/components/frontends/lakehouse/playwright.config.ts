import { defineConfig, devices } from '@playwright/test';

// Hermetic e2e for the whole lakehouse zone — all four areas (e2e/data, e2e/lineage, e2e/models,
// e2e/admin), which used to be four separate zones each running their own dev server and browser.
// Every `/capi/**` + `/api/**` response is mocked via page.route, so no live backend is needed: the dev
// server runs the real SSR + client hydration under this zone's `/lakehouse` base path, and the
// browser's backend calls are the only thing stubbed. Specs `goto` the base-prefixed routes
// (`/lakehouse/data/...`, `/lakehouse/admin/...`, …), so a hop between AREAS is now exercised as the
// soft navigation it became.
//
// TWO app servers, because the admin area's suite is the one that exercises the REAL login gate: it
// needs OIDC configured (auth ON) plus a mock catalog for the control-events feed's server-side
// query.live poll. The other three areas run against an auth-OFF server, exactly as they did before
// the merge — one zone cannot be auth-ON and auth-OFF at once, and that split predates this config.
// Net it is still two dev servers where there used to be four.
const AUTH_OFF = 'http://localhost:5294';
const AUTH_ON = 'http://localhost:5295';
/** The mock catalog. 5297, NOT 5296: a locally parallel run with `reuseExistingServer` must not
 *  silently "reuse" some other dev server as the catalog (audit finding, carried over). */
const MOCK_CATALOG_PORT = 5297;

export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: { baseURL: AUTH_OFF, trace: 'on-first-retry' },
	webServer: [
		{
			// Dedicated e2e ports (not the 5174 microfrontends dev port) so a running composition can't clash.
			command: 'bun run dev --port 5294 --strictPort',
			port: 5294,
			reuseExistingServer: !process.env.CI,
			timeout: 120_000,
		},
		{
			command: 'bun run dev --port 5295 --strictPort',
			port: 5295,
			reuseExistingServer: !process.env.CI,
			timeout: 120_000,
			env: {
				OIDC_ISSUER: 'http://dex.test/dex',
				OIDC_CLIENT_ID: 'lance-admin-e2e',
				OIDC_REDIRECT_URI: `${AUTH_ON}/auth/callback`,
				CATALOG_API: `http://localhost:${MOCK_CATALOG_PORT}`,
			},
		},
		{
			command: 'bun e2e/admin/mock-catalog.ts',
			port: MOCK_CATALOG_PORT,
			reuseExistingServer: !process.env.CI,
			timeout: 30_000,
		},
	],
	projects: [
		// Warmup compiles the heavy routes ONCE before the parallel suite: with fullyParallel on a big box
		// (~32 workers) a cold Vite cache (e.g. right after a reformat) makes the whole first wave of tests
		// starve behind the initial compile and time out at 30s in a bundle — flaky counts per run.
		{ name: 'warmup', testMatch: /warmup\.setup\.ts/, use: { baseURL: AUTH_OFF } },
		{
			name: 'chromium',
			testIgnore: /e2e\/admin\//,
			use: { ...devices['Desktop Chrome'], baseURL: AUTH_OFF },
			dependencies: ['warmup'],
		},
		{
			// The admin area against the auth-ON server. Its specs sign in per-test and that server is a
			// separate compile, so it does not share the auth-OFF warmup.
			name: 'chromium-admin',
			testMatch: /e2e\/admin\/.*\.spec\.ts/,
			use: { ...devices['Desktop Chrome'], baseURL: AUTH_ON },
		},
	],
});
