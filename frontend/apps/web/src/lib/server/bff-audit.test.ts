// BFF contract (#77): the audit viewer is session-gated (401 when auth on + no session), queries GreptimeDB
// server-side, and parses opentelemetry_logs rows into audit events — robust to the attribute column names —
// with server-side outcome/subject filtering.
import { describe, expect, mock, test } from "bun:test";

mock.module("$env/dynamic/private", () => ({ env: { GREPTIME_API: "http://greptime.test" } }));

const { GET } = await import("../../routes/api/audit/+server");

const SQL_RESPONSE = {
	output: [
		{
			records: {
				schema: {
					column_schemas: [
						{ name: "timestamp" },
						{ name: "body" },
						{ name: "audit.action" },
						{ name: "audit.outcome" },
						{ name: "audit.subject" },
						{ name: "audit.resource" },
					],
				},
				rows: [
					["2026-07-20T10:00:00Z", "audit", "can_drop", "DENY", "user:bob", "table:db1$t"],
					["2026-07-20T09:00:00Z", "audit", "can_read_data", "ALLOW", "user:alice", "table:db1$t"],
				],
			},
		},
	],
};

function drive(query: string, opts: { session?: boolean; authEnabled?: boolean } = {}) {
	let sqlSent = "";
	const event = {
		url: new URL(`http://bff/api/audit?${query}`),
		fetch: async (u: string, init: RequestInit) => {
			sqlSent = String(init.body ?? "");
			return new Response(JSON.stringify(SQL_RESPONSE), {
				status: 200,
				headers: { "content-type": "application/json" },
			});
		},
		locals: {
			authEnabled: opts.authEnabled ?? true,
			session: opts.session ? { accessToken: "tok" } : null,
		},
	};
	return { run: () => GET(event as unknown as Parameters<typeof GET>[0]), sqlSent: () => sqlSent };
}

describe("audit BFF (#77)", () => {
	test("auth-on with no session fails closed to 401", async () => {
		const res = await drive("", { session: false }).run();
		expect(res.status).toBe(401);
	});

	test("parses opentelemetry_logs rows into audit events", async () => {
		const d = drive("", { session: true });
		const res = await d.run();
		expect(res.status).toBe(200);
		const body = (await res.json()) as {
			events: { action: string; outcome: string; subject: string }[];
		};
		expect(body.events.length).toBe(2);
		expect(body.events[0]).toMatchObject({
			action: "can_drop",
			outcome: "DENY",
			subject: "user:bob",
		});
		expect(d.sqlSent()).toContain("opentelemetry_logs");
		expect(d.sqlSent()).toContain("body");
	});

	test("outcome filter narrows the events server-side", async () => {
		const res = await drive("outcome=DENY", { session: true }).run();
		const body = (await res.json()) as { events: { outcome: string }[] };
		expect(body.events.length).toBe(1);
		expect(body.events[0].outcome).toBe("DENY");
	});

	test("subject filter is a case-insensitive substring", async () => {
		const res = await drive("subject=ALICE", { session: true }).run();
		const body = (await res.json()) as { events: { subject: string }[] };
		expect(body.events.length).toBe(1);
		expect(body.events[0].subject).toBe("user:alice");
	});
});
