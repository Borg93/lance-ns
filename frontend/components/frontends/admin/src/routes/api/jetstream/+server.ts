import { env } from '$env/dynamic/private';
import { json } from '@sveltejs/kit';
import { parse } from '@rask/api';
import { RawJszSchema, type JetStreamOverview } from '$lib/jetstream';
import type { RequestHandler } from './$types';

// `/api/jetstream` — read-only JetStream visibility for the /streams admin panel. The NATS HTTP monitor
// port (8222) is unauthenticated by design and reachable only over its in-cluster ClusterIP, so — exactly
// like the GreptimeDB seam behind /api/audit — this BFF's admin gate is the ONLY gate: the monitor URL is
// never exposed to the browser or the ingress. We fetch `/jsz` server-side, parse it, and return a trimmed
// typed overview (the raw payload is ~29 KB; the browser gets only what the panel renders). No mutation
// surface exists on the monitor endpoints, matching the read-only viewer posture.
//
// Session-gated on a governed stack (mirroring /api/audit): stream/consumer topology describes the whole
// estate's event fabric, so an anonymous front-door caller must not read it; auth-off dev answers openly.
// 501 when NATS_MONITOR_API is unset (no NATS monitor wired).
const NATS_MONITOR_API = env.NATS_MONITOR_API ?? '';
// The view is estate-wide, so it is ADMIN-only — not merely authenticated. We reuse the one admin door the
// estate already owns: the medallion produce door's side-effect-free GET /authorize (a signed-in
// `can_administer` project admin, or the service/dev paths). We bearer-FORWARD the user's token (never a
// service token) and only query the NATS monitor if it returns 200.
const MEDALLION_API = env.MEDALLION_API ?? '';

// Returns null when the caller is an authorized admin; otherwise the {status, detail} to answer with.
async function adminGate(
	fetchFn: typeof fetch,
	accessToken: string,
): Promise<{ status: number; detail: string } | null> {
	if (!MEDALLION_API) {
		// Governed stack but no admin authority wired → fail closed rather than leak the topology.
		return { status: 503, detail: 'jetstream admin authorization is unavailable' };
	}
	try {
		const res = await fetchFn(`${MEDALLION_API}/authorize`, {
			headers: { authorization: `Bearer ${accessToken}` },
		});
		if (res.ok) return null;
		if (res.status === 403)
			return { status: 403, detail: 'the stream view is admin-only (project admin required)' };
		if (res.status === 401) return { status: 401, detail: 'sign in to view JetStream streams' };
		return { status: 503, detail: 'jetstream admin authorization is unavailable' };
	} catch (err) {
		console.error(`api jetstream admin-gate upstream failure: ${String(err)}`);
		return { status: 503, detail: 'jetstream admin authorization is unavailable' };
	}
}

export const GET: RequestHandler = async ({ fetch, locals }) => {
	if (locals.authEnabled && !locals.session) {
		return json({ detail: 'sign in to view JetStream streams' }, { status: 401 });
	}
	// Authorization (not just authentication): a governed, signed-in caller must be a project admin — else
	// any reader could map the estate's whole event fabric. Auth-off dev skips the gate (open).
	if (locals.authEnabled && locals.session) {
		const denied = await adminGate(fetch, locals.session.accessToken);
		if (denied) return json({ detail: denied.detail }, { status: denied.status });
	}
	if (!NATS_MONITOR_API) {
		return json({ detail: 'jetstream monitor not configured' }, { status: 501 });
	}
	try {
		const res = await fetch(`${NATS_MONITOR_API}/jsz?streams=true&consumers=true&config=true`);
		if (!res.ok) {
			return json({ detail: `nats monitor ${res.status}` }, { status: 502 });
		}
		const raw = parse(RawJszSchema, await res.json());
		// Trim: flatten account_details[].stream_detail[] (single $G account today, but shape-robust) and
		// keep only what the panel renders — the browser never sees the raw monitor payload.
		const streams = raw.account_details
			.flatMap((account) => account.stream_detail)
			.map((s) => ({
				name: s.name,
				subjects: s.config.subjects,
				retention: s.config.retention,
				storage: s.config.storage,
				max_age_ns: s.config.max_age,
				max_msgs: s.config.max_msgs,
				max_bytes: s.config.max_bytes,
				num_replicas: s.config.num_replicas,
				state: s.state,
				consumers: s.consumer_detail.map((c) => ({
					name: c.name,
					durable: Boolean(c.config?.durable_name),
					deliver_group: c.config?.deliver_group,
					num_pending: c.num_pending,
					num_ack_pending: c.num_ack_pending,
					num_redelivered: c.num_redelivered,
					last_active: c.delivered?.last_active,
				})),
			}))
			.sort((a, b) => a.name.localeCompare(b.name));
		const overview: JetStreamOverview = {
			now: raw.now,
			totals: {
				streams: raw.streams,
				consumers: raw.consumers,
				messages: raw.messages,
				bytes: raw.bytes,
			},
			streams,
		};
		return json(overview);
	} catch (err) {
		console.error(`api jetstream proxy upstream failure: ${String(err)}`);
		return json({ detail: String(err) }, { status: 502 });
	}
};
