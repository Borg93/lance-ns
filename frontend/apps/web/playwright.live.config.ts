import { defineConfig, devices } from "@playwright/test";

// LIVE e2e against the DEPLOYED web pod (rask tests/e2e convention) — no mocks, no dev server.
// Point LANCE_E2E_WEB_URL at a port-forward of svc/<release>-web (make e2e-web does this) and the
// suite asserts every route hydrates cleanly and the BFF proxies round-trip on the real stack.
// The hermetic suite (playwright.config.ts + e2e/) stays the CI default; this one needs a cluster.
export default defineConfig({
	testDir: "./e2e-live",
	use: {
		baseURL: process.env.LANCE_E2E_WEB_URL ?? "http://localhost:3000",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
	},
	reporter: [["list"]],
	projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
