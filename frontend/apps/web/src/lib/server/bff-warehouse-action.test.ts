// BFF security contract (#63): the warehouse-action route is a NARROW, session-only proxy — an explicit
// action allowlist (never a blanket write proxy — the confused-deputy guard), fail-closed to 401 when
// auth is on and there is no session, and it forwards ONLY the signed-in user's bearer. These are the
// exact properties an attacker would probe, so they get a unit test rather than living only in review.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

// Import AFTER the mock so the handler's static `$env/dynamic/private` import resolves to the stub.
// No `.ts` extension — svelte-check (tsc) rejects it; bun resolves `+server` to the file.
const { POST } = await import("../../routes/capi/v1/warehouses/[id]/[action]/+server");

type Handled = { url: string; auth: string | undefined };

function drive(action: string, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	const calls: Handled[] = [];
	const event = {
		params: { id: "wh 1", action },
		request: new Request("http://bff/x", { method: "POST", body: "" }),
		fetch: (url: string, init: RequestInit) => {
			const headers = (init.headers ?? {}) as Record<string, string>;
			calls.push({ url, auth: headers["authorization"] });
			return Promise.resolve(
				new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
			);
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => POST(event as unknown as Parameters<typeof POST>[0]), calls };
}

describe("warehouse-action BFF", () => {
	test("a non-allowlisted action is 404 and NEVER proxies", async () => {
		const d = drive("deregister", { session: true });
		const res = await d.run();
		expect(res.status).toBe(404);
		expect(d.calls.length).toBe(0); // the guard short-circuits before any upstream call
	});

	test("auth-on with no session fails closed to 401 and never proxies", async () => {
		const d = drive("activate", { session: false, authEnabled: true });
		const res = await d.run();
		expect(res.status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("an allowlisted action forwards to the catalog with the session bearer (id url-encoded)", async () => {
		const d = drive("deactivate", { session: true });
		const res = await d.run();
		expect(res.status).toBe(200);
		expect(d.calls.length).toBe(1);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/warehouses/wh%201/deactivate");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});

	test("auth-off forwards without a bearer (dev / open stack)", async () => {
		const d = drive("activate", { session: false, authEnabled: false });
		const res = await d.run();
		expect(res.status).toBe(200);
		expect(d.calls[0].auth).toBeUndefined();
	});
});
