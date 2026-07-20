import { env } from "$env/dynamic/private";
import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

// #77 admin audit-log viewer — the same-origin BFF over the #41 compliance trail. Audit events are emitted
// on the dedicated `lance.audit` logger (services/common/audit.py) as structured logs → OTLP → GreptimeDB's
// `opentelemetry_logs` table (body='audit', with audit.action/outcome/subject/resource attributes). This
// queries GreptimeDB's SQL endpoint server-side (proven shape, docs/KIND-RUNBOOK.md) and returns parsed
// events, so the /audit page renders the real trail without exposing a credential to the browser (GreptimeDB
// over its in-cluster ClusterIP; the §5e edge auth is not in this path). Read-only, no write surface.
//
// Session-gated on a governed stack (mirroring /api/experiments): the trail lists who did what across the
// estate, so an anonymous front-door caller must not read it; without OIDC (auth-off dev) it answers openly.
// 501 when GREPTIME_API is unset (no observability stack).
const GREPTIME_API = env.GREPTIME_API ?? "";

// GreptimeDB /v1/sql response: { output: [ { records: { schema: { column_schemas: [{name}] }, rows: [[...]] } } ] }.
type SqlResponse = {
	output?: { records?: { schema?: { column_schemas?: { name: string }[] }; rows?: unknown[][] } }[];
};
type AuditEvent = {
	timestamp: string;
	action: string;
	outcome: string;
	subject: string;
	resource: string;
};

// Map a GreptimeDB row (by column name) to an audit event — robust to whether OTLP attributes are flattened
// as `audit.action` columns or land under bare `action`/etc. names.
function pick(row: Record<string, unknown>, ...keys: string[]): string {
	for (const k of keys) {
		const v = row[k];
		if (v !== undefined && v !== null && v !== "") return String(v);
	}
	return "";
}

export const GET: RequestHandler = async ({ url, fetch, locals }) => {
	if (locals.authEnabled && !locals.session) {
		return json({ detail: "sign in to view the audit trail" }, { status: 401 });
	}
	if (!GREPTIME_API) {
		return json(
			{ detail: "the audit viewer requires the observability stack (GreptimeDB)" },
			{ status: 501 },
		);
	}
	// Proven query shape (docs/KIND-RUNBOOK.md): filter to audit records, newest first, bounded. The
	// finer action/outcome/subject/resource + time filters are applied below over the returned columns, so
	// the SQL never depends on an attribute column name that may differ across GreptimeDB OTLP versions.
	const sql =
		"SELECT * FROM opentelemetry_logs WHERE body = 'audit' ORDER BY timestamp DESC LIMIT 500";
	try {
		const res = await fetch(`${GREPTIME_API}/v1/sql?db=public`, {
			method: "POST",
			headers: { "content-type": "application/x-www-form-urlencoded" },
			body: `sql=${encodeURIComponent(sql)}`,
		});
		if (!res.ok) {
			return json({ detail: `greptime ${res.status}` }, { status: 502 });
		}
		const body = (await res.json()) as SqlResponse;
		const records = body.output?.[0]?.records;
		const cols = (records?.schema?.column_schemas ?? []).map((c) => c.name);
		const rows = records?.rows ?? [];
		let events: AuditEvent[] = rows.map((r) => {
			const o: Record<string, unknown> = {};
			cols.forEach((c, i) => (o[c] = r[i]));
			return {
				timestamp: pick(o, "timestamp", "time"),
				action: pick(o, "audit.action", "action"),
				outcome: pick(o, "audit.outcome", "outcome"),
				subject: pick(o, "audit.subject", "subject"),
				resource: pick(o, "audit.resource", "resource"),
			};
		});
		// Post-filter over the parsed events (case-insensitive substring for subject/resource, exact for the
		// low-cardinality action/outcome), so the query shape stays fixed + proven.
		const f = (k: string) => url.searchParams.get(k)?.trim().toLowerCase() ?? "";
		const [action, outcome, subject, resource] = ["action", "outcome", "subject", "resource"].map(
			f,
		);
		if (action) events = events.filter((e) => e.action.toLowerCase() === action);
		if (outcome) events = events.filter((e) => e.outcome.toLowerCase() === outcome);
		if (subject) events = events.filter((e) => e.subject.toLowerCase().includes(subject));
		if (resource) events = events.filter((e) => e.resource.toLowerCase().includes(resource));
		return json({ events });
	} catch (err) {
		console.error(`api audit proxy upstream failure: ${String(err)}`);
		return json({ detail: String(err) }, { status: 502 });
	}
};
