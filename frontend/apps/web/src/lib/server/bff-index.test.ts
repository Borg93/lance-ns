// BFF security contract (#73): the index create/drop routes are narrow session-only proxies — fail-closed
// to 401 when auth is on and there's no session, forward ONLY the signed-in user's bearer, and the create
// route dispatches to create_scalar_index vs create_index by the ?scalar flag.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

const { POST: CREATE } = await import("../../routes/capi/v1/table/[id]/index/create/+server");
const { POST: DROP } = await import("../../routes/capi/v1/table/[id]/index/[name]/drop/+server");

function createEvent(opts: { scalar: boolean; session?: boolean; authEnabled?: boolean }) {
	const calls: { url: string; auth: string | undefined }[] = [];
	const event = {
		params: { id: "db1$t" },
		url: new URL(`http://bff/x?scalar=${opts.scalar ? 1 : 0}`),
		request: new Request("http://bff/x", {
			method: "POST",
			body: JSON.stringify({ column: "vec", index_type: opts.scalar ? "BTREE" : "IVF_PQ" }),
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
	return { run: () => CREATE(event as unknown as Parameters<typeof CREATE>[0]), calls };
}

describe("index BFF", () => {
	test("create with no session fails closed to 401", async () => {
		const e = createEvent({ scalar: true, session: false });
		expect((await e.run()).status).toBe(401);
		expect(e.calls.length).toBe(0);
	});

	test("scalar=1 dispatches to create_scalar_index with the bearer", async () => {
		const e = createEvent({ scalar: true, session: true });
		expect((await e.run()).status).toBe(200);
		expect(e.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/create_scalar_index");
		expect(e.calls[0].auth).toBe("Bearer tok");
	});

	test("scalar=0 dispatches to create_index (the vector family)", async () => {
		const e = createEvent({ scalar: false, session: true });
		expect((await e.run()).status).toBe(200);
		expect(e.calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/create_index");
	});

	test("drop forwards to index/{name}/drop with the bearer", async () => {
		const calls: { url: string; auth: string | undefined }[] = [];
		const event = {
			params: { id: "db1$t", name: "vec_idx" },
			request: new Request("http://bff/x", { method: "POST", body: "" }),
			fetch: async (url: string, init: RequestInit) => {
				calls.push({
					url,
					auth: ((init.headers ?? {}) as Record<string, string>)["authorization"],
				});
				return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
			},
			locals: { authEnabled: true, session: { accessToken: "tok" } },
		};
		const res = await DROP(event as unknown as Parameters<typeof DROP>[0]);
		expect(res.status).toBe(200);
		expect(calls[0].url).toBe("http://catalog.test/v1/table/db1%24t/index/vec_idx/drop");
		expect(calls[0].auth).toBe("Bearer tok");
	});
});
