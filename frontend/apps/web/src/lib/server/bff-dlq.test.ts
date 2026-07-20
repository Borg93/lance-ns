// BFF security contract (#83): the DLQ replay route is a narrow session-only write beside the GET-only /api
// lineage proxy. It fails closed to 401 when auth is on and there's no session, and forwards ONLY the
// signed-in user's bearer (never a service token) so the lineage writer gate is enforced against a real user.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { LINEAGE_API: "http://lineage.test" } }));

const { POST } = await import("../../routes/api/admin/dlq/[run_id]/replay/+server");

function drive(runId: string, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	const calls: { url: string; method: string; headers: Record<string, string> }[] = [];
	const event = {
		params: { run_id: runId },
		fetch: async (url: string, init: RequestInit) => {
			calls.push({
				url,
				method: init.method ?? "GET",
				headers: (init.headers ?? {}) as Record<string, string>,
			});
			return new Response(JSON.stringify({ status: "replayed", run_id: runId }), {
				status: 200,
				headers: { "content-type": "application/json" },
			});
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => POST(event as unknown as Parameters<typeof POST>[0]), calls };
}

describe("DLQ replay BFF (#83)", () => {
	test("auth-on with no session fails closed to 401 and never proxies", async () => {
		const d = drive("r1", { session: false });
		expect((await d.run()).status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("a signed-in user's replay forwards the bearer to the lineage replay route", async () => {
		const d = drive("run-abc", { session: true });
		const res = await d.run();
		expect(res.status).toBe(200);
		expect(d.calls[0].url).toBe("http://lineage.test/admin/dlq/run-abc/replay");
		expect(d.calls[0].method).toBe("POST");
		expect(d.calls[0].headers["authorization"]).toBe("Bearer tok");
	});

	test("the run id is URL-encoded into the upstream path", async () => {
		const d = drive("weird/run id", { session: true });
		await d.run();
		expect(d.calls[0].url).toBe("http://lineage.test/admin/dlq/weird%2Frun%20id/replay");
	});

	test("auth-off forwards without a bearer AND never attaches a service token", async () => {
		const d = drive("r1", { session: false, authEnabled: false });
		expect((await d.run()).status).toBe(200);
		expect(d.calls[0].headers["authorization"]).toBeUndefined();
		expect(d.calls[0].headers["dapr-api-token"]).toBeUndefined();
	});
});
