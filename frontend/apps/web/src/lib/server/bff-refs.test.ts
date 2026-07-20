// BFF security contract (#74): the branch/tag mutation routes are narrow session-only proxies — an explicit
// action allowlist, fail-closed to 401 when auth is on and there's no session, forwarding ONLY the user's
// bearer to the catalog's branches/{action} + tags/{action}.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { CATALOG_API: "http://catalog.test" } }));

const { POST: BRANCH } = await import("../../routes/capi/v1/table/[id]/branches/[action]/+server");
const { POST: TAG } = await import("../../routes/capi/v1/table/[id]/tags/[action]/+server");

function drive(
	handler: typeof BRANCH,
	action: string,
	opts: { session?: boolean; authEnabled?: boolean } = {},
) {
	const calls: { url: string; auth: string | undefined }[] = [];
	const event = {
		params: { id: "db1$t", action },
		request: new Request("http://bff/x", {
			method: "POST",
			body: JSON.stringify({ name: "b" }),
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
	return { run: () => handler(event as unknown as Parameters<typeof handler>[0]), calls };
}

describe("branch/tag mutation BFF (#74)", () => {
	test("non-allowlisted branch action is 404 and never proxies", async () => {
		const d = drive(BRANCH, "rebase", { session: true });
		expect((await d.run()).status).toBe(404);
		expect(d.calls.length).toBe(0);
	});

	test("non-allowlisted tag action is 404", async () => {
		const d = drive(TAG as unknown as typeof BRANCH, "rename", { session: true });
		expect((await d.run()).status).toBe(404);
	});

	test("auth-on no session fails closed to 401", async () => {
		const d = drive(BRANCH, "create", { session: false });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("branch create/delete forward with the bearer", async () => {
		for (const a of ["create", "delete"]) {
			const d = drive(BRANCH, a, { session: true });
			expect((await d.run()).status).toBe(200);
			expect(d.calls[0].url).toBe(`http://catalog.test/v1/table/db1%24t/branches/${a}`);
			expect(d.calls[0].auth).toBe("Bearer tok");
		}
	});

	test("tag delete/update forward with the bearer", async () => {
		for (const a of ["delete", "update"]) {
			const d = drive(TAG as unknown as typeof BRANCH, a, { session: true });
			expect((await d.run()).status).toBe(200);
			expect(d.calls[0].url).toBe(`http://catalog.test/v1/table/db1%24t/tags/${a}`);
		}
	});
});
