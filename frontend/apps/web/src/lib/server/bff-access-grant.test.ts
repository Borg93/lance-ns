// BFF security contract (#72): the access grant/revoke routes are narrow session-only proxies — fail-closed
// to 401 when auth is on and there's no session, and they forward ONLY the signed-in user's bearer to the
// catalog (so its owner-tier gate is enforced against a real user, never the web tier's identity).
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

// grant/revoke handlers carry distinct route-specific $types (the route-id phantom differs), so REVOKE is
// cast to GRANT's handler type at its call site — the runtime shape is identical.
const { POST: GRANT } = await import("../../routes/capi/v1/table/[id]/access/grant/+server");
const { POST: REVOKE } = await import("../../routes/capi/v1/table/[id]/access/revoke/+server");
const { POST: GRAPH } = await import("../../routes/capi/v1/table/[id]/access/graph/+server");

type Handled = { url: string; auth: string | undefined; body: string };

function drive(handler: typeof GRANT, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	const calls: Handled[] = [];
	const event = {
		params: { id: "db1$users" },
		request: new Request("http://bff/x", {
			method: "POST",
			body: JSON.stringify({ user: "bob", relation: "reader" }),
			headers: { "content-type": "application/json" },
		}),
		fetch: async (url: string, init: RequestInit) => {
			const headers = (init.headers ?? {}) as Record<string, string>;
			calls.push({ url, auth: headers["authorization"], body: String(init.body ?? "") });
			return new Response(
				'{"object":"table:db1$users","user":"user:bob","relation":"reader","granted":true}',
				{
					status: 200,
					headers: { "content-type": "application/json" },
				},
			);
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => handler(event as unknown as Parameters<typeof handler>[0]), calls };
}

describe("access grant/revoke BFF", () => {
	test("auth-on with no session fails closed to 401 and never proxies", async () => {
		const d = drive(GRANT, { session: false, authEnabled: true });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("grant forwards to the catalog with the session bearer + body", async () => {
		const d = drive(GRANT, { session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24users/access/grant");
		expect(d.calls[0].auth).toBe("Bearer tok");
		expect(JSON.parse(d.calls[0].body)).toEqual({ user: "bob", relation: "reader" });
	});

	test("revoke forwards to the revoke endpoint with the bearer", async () => {
		const d = drive(REVOKE as unknown as typeof GRANT, { session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24users/access/revoke");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});

	test("auth-off forwards without a bearer (dev / open stack)", async () => {
		const d = drive(GRANT, { session: false, authEnabled: false });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].auth).toBeUndefined();
	});
});

describe("access graph BFF (#81)", () => {
	function driveGraph(opts: { session?: boolean; authEnabled?: boolean } = {}) {
		const calls: { url: string; auth: string | undefined }[] = [];
		const event = {
			params: { id: "db1$t" },
			request: new Request("http://bff/x", { method: "POST", body: "" }),
			fetch: async (url: string, init: RequestInit) => {
				calls.push({
					url,
					auth: ((init.headers ?? {}) as Record<string, string>)["authorization"],
				});
				return new Response('{"object":"table:db1$t","nodes":[],"edges":[]}', {
					status: 200,
					headers: { "content-type": "application/json" },
				});
			},
			locals: {
				authEnabled: opts.authEnabled ?? true,
				session: opts.session ? { accessToken: "tok" } : null,
			},
		};
		return { run: () => GRAPH(event as unknown as Parameters<typeof GRAPH>[0]), calls };
	}

	test("auth-on with no session fails closed to 401", async () => {
		const d = driveGraph({ session: false });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("forwards to the catalog graph endpoint with the session bearer", async () => {
		const d = driveGraph({ session: true });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/access/graph");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});
});
