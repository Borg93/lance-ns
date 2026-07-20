// BFF security contract (#74): the column-op route is a narrow session-only proxy — an explicit allowlist
// (add|alter|drop → the catalog's {op}_columns), fail-closed to 401 when auth is on and there's no session,
// and it forwards ONLY the signed-in user's bearer (so the catalog's writer-tier gate is enforced).
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

const { POST } = await import("../../routes/capi/v1/table/[id]/columns/[op]/+server");

function drive(op: string, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	const calls: { url: string; auth: string | undefined }[] = [];
	const event = {
		params: { id: "db1$t", op },
		request: new Request("http://bff/x", {
			method: "POST",
			body: JSON.stringify({ columns: ["x"] }),
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

describe("column-ops BFF (#74)", () => {
	test("a non-allowlisted op is 404 and NEVER proxies", async () => {
		const d = drive("truncate", { session: true });
		expect((await d.run()).status).toBe(404);
		expect(d.calls.length).toBe(0);
	});

	test("auth-on with no session fails closed to 401", async () => {
		const d = drive("drop", { session: false });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("every allowlisted op maps to its catalog route with the bearer (#74 incl. tail)", async () => {
		for (const [op, upstream] of [
			["add", "add_columns"],
			["alter", "alter_columns"],
			["drop", "drop_columns"],
			// #74 tail — per-field + table-level metadata (the latter a two-segment upstream that composes).
			["field-meta", "update_field_metadata"],
			["table-meta", "schema_metadata/update"],
		]) {
			const d = drive(op, { session: true });
			expect((await d.run()).status).toBe(200);
			expect(d.calls[0].url).toBe(`http://catalog.test/v1/table/db1%24t/${upstream}`);
			expect(d.calls[0].auth).toBe("Bearer tok");
		}
	});

	test("auth-off forwards without a bearer (dev / open stack)", async () => {
		const d = drive("add", { session: false, authEnabled: false });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].auth).toBeUndefined();
	});
});
