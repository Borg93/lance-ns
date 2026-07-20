// BFF security contract (#63/#64): the medallion trigger route is a NARROW, session-only proxy — an
// explicit action allowlist (produce/train, never a blanket write proxy), fail-closed to 401 when auth is
// on and there is no session, and it forwards ONLY the signed-in user's bearer to lance-ray (never the
// service token). These are the exact properties an attacker would probe, so they get a unit test.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { MEDALLION_API: "http://lance-ray.test" } }));

// Import AFTER the mock so the handler's static `$env/dynamic/private` import resolves to the stub.
const { POST } = await import("../../routes/medallion/[action]/+server");

type Handled = { url: string; auth: string | undefined; idem: string | undefined };

function drive(
	action: string,
	opts: { session?: boolean; authEnabled?: boolean; idem?: string } = {},
) {
	const calls: Handled[] = [];
	const reqHeaders: Record<string, string> = { "content-type": "application/json" };
	if (opts.idem) reqHeaders["idempotency-key"] = opts.idem;
	const event = {
		params: { action },
		request: new Request("http://bff/x", { method: "POST", body: "", headers: reqHeaders }),
		fetch: (url: string, init: RequestInit) => {
			const headers = (init.headers ?? {}) as Record<string, string>;
			calls.push({ url, auth: headers["authorization"], idem: headers["idempotency-key"] });
			return Promise.resolve(
				new Response('{"status":"ok","token":"t1"}', {
					status: 202,
					headers: { "content-type": "application/json" },
				}),
			);
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => POST(event as unknown as Parameters<typeof POST>[0]), calls };
}

describe("medallion trigger BFF", () => {
	test("a non-allowlisted action is 404 and NEVER proxies", async () => {
		const d = drive("delete", { session: true });
		const res = await d.run();
		expect(res.status).toBe(404);
		expect(d.calls.length).toBe(0); // the guard short-circuits before any upstream call
	});

	test("auth-on with no session fails closed to 401 and never proxies", async () => {
		const d = drive("produce", { session: false, authEnabled: true });
		const res = await d.run();
		expect(res.status).toBe(401);
		expect(d.calls.length).toBe(0);
	});

	test("produce forwards to lance-ray with the session bearer", async () => {
		const d = drive("produce", { session: true });
		const res = await d.run();
		expect(res.status).toBe(202);
		expect(d.calls.length).toBe(1);
		expect(d.calls[0].url).toBe("http://lance-ray.test/produce");
		expect(d.calls[0].auth).toBe("Bearer tok");
	});

	test("train forwards to lance-ray and passes the idempotency key through", async () => {
		const d = drive("train", { session: true, idem: "run-42" });
		const res = await d.run();
		expect(res.status).toBe(202);
		expect(d.calls[0].url).toBe("http://lance-ray.test/train");
		expect(d.calls[0].auth).toBe("Bearer tok");
		expect(d.calls[0].idem).toBe("run-42");
	});

	test("auth-off forwards without a bearer (dev / open stack)", async () => {
		const d = drive("produce", { session: false, authEnabled: false });
		const res = await d.run();
		expect(res.status).toBe(202);
		expect(d.calls[0].auth).toBeUndefined();
	});
});
