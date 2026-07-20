// BFF security contract (#75): the maintenance route is a narrow session-only proxy — an explicit action
// allowlist (preview | run), fail-closed to 401 when auth is on and there's no session, and it forwards
// ONLY the signed-in user's bearer (so the catalog's owner-tier gate is enforced against a real user).
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

const { POST } = await import("../../routes/capi/v1/table/[id]/maintenance/[action]/+server");

function drive(action: string, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	const calls: { url: string; auth: string | undefined }[] = [];
	const event = {
		params: { id: "db1$t", action },
		request: new Request("http://bff/x", {
			method: "POST",
			body: JSON.stringify({ retain_versions: 3 }),
			headers: { "content-type": "application/json" },
		}),
		fetch: async (url: string, init: RequestInit) => {
			calls.push({ url, auth: ((init.headers ?? {}) as Record<string, string>)["authorization"] });
			return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => POST(event as unknown as Parameters<typeof POST>[0]), calls };
}

describe("maintenance BFF (#75)", () => {
	test("a non-allowlisted action is 404 and NEVER proxies", async () => {
		const d = drive("nuke", { session: true });
		expect((await d.run()).status).toBe(404);
		expect(d.calls.length).toBe(0);
	});

	test("auth-on with no session fails closed to 401", async () => {
		const d = drive("run", { session: false });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("preview forwards to the catalog with the session bearer", async () => {
		const d = drive("preview", { session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/maintenance/preview");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});

	test("run forwards to the run endpoint", async () => {
		const d = drive("run", { session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/maintenance/run");
	});

	test("compact forwards to the compact endpoint (#76)", async () => {
		const d = drive("compact", { session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/maintenance/compact");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});

	test("auth-off forwards without a bearer (dev / open stack)", async () => {
		const d = drive("preview", { session: false, authEnabled: false });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].auth).toBeUndefined();
	});
});
