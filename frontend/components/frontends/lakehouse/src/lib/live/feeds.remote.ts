import { error } from '@sveltejs/kit';
import { getRequestEvent, query } from '$app/server';
import { env } from '$env/dynamic/private';
import { fetchMe, parse } from '@repo/api';
import * as v from 'valibot';

/**
 * The zone's LIVE CURSORS — `query.live` generators that say *when the estate changed*, so a panel can
 * re-read instead of waking on a timer.
 *
 * Before this, thirteen files in this zone ran `$effect(() => { load(); setInterval(load, 5000) })`. That
 * is a blind poll: it re-reads whether or not anything happened, every panel keeps its own clock (so two
 * views of the same entity disagree for up to 5s), and the cost is paid in full every tick. Measured on
 * the live estate as alice, through `:8090`:
 *
 *     GET /api/events?limit=200                 471_217 bytes
 *     GET /api/events?limit=200&summary=true     46_625 bytes
 *     GET /api/events?limit=1&summary=true          245 bytes   <- the cursor probe
 *     GET /api/runs                             330_103 bytes
 *
 * So the probe below is ~1900x cheaper than the read it gates, and on an idle estate the browser receives
 * nothing at all. The generator runs on the zone (SvelteKit/Bun) server and holds the cursor; SvelteKit
 * streams each yield and owns reconnect (exponential backoff + on `navigator.onLine`) — no hand-rolled
 * SSE, no client cursor bookkeeping. This is `admin/remote/admin.remote.ts`'s discipline (server-held
 * cursor, change-only yields) applied to the read side.
 *
 * Two sources, deliberately, and each surface picks the one that actually reports its changes:
 *
 *  - `lineageFeed` — `GET /events?limit=1&summary=true` on the lineage plane. **Governed per subject**:
 *    an event is returned only if the caller `can_get_metadata` on every dataset it references, so a
 *    non-admin gets a real live feed with no backend change and never learns that an event they cannot
 *    see exists. Everything data-shaped (tables, namespaces, datasets, jobs, runs, columns, models, the
 *    lineage DAG, the outbox backlog) hangs off this.
 *  - `controlCursor` — `GET /v1/events?since=` on the catalog control plane, which is **estate-admin
 *    gated** (`can_observe_events` on the FGA root) and reports *governance* mutations: warehouses,
 *    tenants, grants, promotions. Those never touch a dataset, so they never move the lineage cursor;
 *    the admin surfaces that render them use this instead.
 *
 * KEEPALIVE. A change-only stream is by definition silent on an idle estate, and both the edge
 * (`proxy-read-timeout`) and the zone's own Bun server (`IDLE_TIMEOUT`) sever an idle stream. So a cursor
 * is re-yielded every `KEEPALIVE_MS` even when it has not moved: the bytes keep the stream alive, and
 * because the yielded value is an unchanged *primitive*, `.current` is assigned an equal number and no
 * consumer's `$effect` re-runs. Traffic without a re-read.
 *
 * FAIL QUIET. A probe that 401s, 403s, times out or cannot connect does NOT throw and does not end the
 * stream — it simply does not tick. Every consuming panel already renders its own honest sign-in /
 * denied / offline state from its own read's status; a cursor that threw would replace that with a
 * boundary error and lose it. `jetstreamCursor` is the one exception, and says why.
 */

const LINEAGE_API = env.LINEAGE_API ?? 'http://localhost:8001';
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';
const NATS_MONITOR_API = env.NATS_MONITOR_API ?? '';

/** How often the server re-probes its cursor. The browser only hears about it when it moved. */
const POLL_MS = 5000;
/** Re-yield an unmoved cursor at least this often, so an idle stream is never severed as idle. */
const KEEPALIVE_MS = 20_000;
/** A probe is a liveness signal, not a page load: bound it so a wedged upstream can't stall the loop. */
const PROBE_TIMEOUT_MS = 4000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// Parsed, not cast, at the wire boundary (the @repo/api parse-don't-validate rule) — a drift in the feed's
// shape must fail here rather than silently read `undefined` as "nothing changed" forever.
const LineageProbeSchema = v.object({ events: v.array(v.object({ seq: v.number() })) });
const ControlProbeSchema = v.object({ cursor: v.number(), reset: v.boolean() });
const JszProbeSchema = v.object({
	streams: v.number(),
	consumers: v.number(),
	messages: v.number(),
});

/**
 * The credential for a lineage read, mirroring `makeLineageProxy` exactly: the signed-in user's bearer
 * when there is one, else the READ-only service credential a governed stack uses to serve reads without a
 * per-user login. Anything else (auth-off dev) sends nothing. Duplicating the proxy's posture rather than
 * hopping through it keeps this a single upstream call, the way `admin.remote.ts` reaches the catalog.
 */
function lineageHeaders(): Record<string, string> {
	const { locals } = getRequestEvent();
	const token = locals.session?.accessToken;
	if (token) return { authorization: `Bearer ${token}` };
	if (env.LINEAGE_SERVICE_TOKEN) {
		return {
			'dapr-api-token': env.LINEAGE_SERVICE_TOKEN,
			'x-lance-service-identity': env.LINEAGE_SERVICE_ID ?? '',
		};
	}
	return {};
}

/** The newest lineage `seq` THIS caller may see, or `null` when the probe did not resolve. */
async function probeLineage(): Promise<number | null> {
	const { fetch } = getRequestEvent();
	try {
		const res = await fetch(`${LINEAGE_API}/events?limit=1&summary=true`, {
			headers: lineageHeaders(),
			signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
		});
		if (!res.ok) return null;
		// An empty visible feed is a real answer (cursor 0), not a failure — it must settle the consumer.
		return parse(LineageProbeSchema, await res.json()).events[0]?.seq ?? 0;
	} catch {
		return null;
	}
}

/**
 * The catalog control-plane cursor: the head of this replica's change-event ring buffer, yielded when it
 * moves. Estate-admin gated at the catalog (`can_observe_events` on the FGA root), so this ticks only for
 * the identities the admin surfaces are already behind.
 *
 * What it yields is a GENERATION, not the buffer head. A `reset` (the caller's cursor fell off the bounded,
 * drop-oldest buffer) is a change the console must re-read on, but it can hand back the very same head
 * number — and an unchanged primitive is exactly what the keepalive relies on NOT waking anyone. So every
 * real move increments a counter of our own, and the keepalive re-yields it unchanged.
 */
export const controlCursor = query.live(async function* (): AsyncGenerator<number> {
	const { fetch, locals } = getRequestEvent();
	const bearer = locals.session?.accessToken;
	const headers: Record<string, string> = bearer ? { authorization: `Bearer ${bearer}` } : {};

	let cursor = 0;
	let generation = 0;
	let settled = false;
	let publishedAt = 0;
	for (;;) {
		let moved = false;
		try {
			const res = await fetch(`${CATALOG_API}/v1/events?since=${cursor}`, {
				headers,
				signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
			});
			if (res.ok) {
				const probe = parse(ControlProbeSchema, await res.json());
				moved = settled && (probe.reset || probe.cursor !== cursor);
				cursor = probe.cursor;
				settled = true;
			}
		} catch {
			/* fail quiet — the panel's own read renders the honest denied/offline state */
		}
		const now = Date.now();
		if (moved) generation++;
		if (settled && (moved || publishedAt === 0 || now - publishedAt >= KEEPALIVE_MS)) {
			publishedAt = now;
			yield generation;
		}
		await sleep(POLL_MS);
	}
});

/**
 * The JetStream cursor — deliberately NOT one of the two event feeds, and this is the surface where that
 * distinction matters most.
 *
 * `/admin/streams` exists to show a wedged or missing consumer. A wedged consumer emits no lineage events
 * and no control events, so driving this panel off either feed would leave it frozen in exactly the
 * incident it is there to catch. Its state is a gauge with no change-event source, so the honest live feed
 * is a server-side probe of the NATS monitor's own totals, yielded only when they move — still no browser
 * timer, still bytes only on change.
 *
 * Unlike the two feeds above this one is NOT self-gating: `/jsz` is unauthenticated by design and reachable
 * only in-cluster, and a remote function is a public HTTP endpoint, so the estate-admin door is made here —
 * the same `fetchMe` check `admin/+layout.server.ts` makes, failing closed on every ambiguity (no token, a
 * 401/403, a timeout, an unreachable catalog, contract drift). Terminal 403, exactly like `controlEvents`.
 */
export const jetstreamCursor = query.live(async function* (): AsyncGenerator<number> {
	const { fetch, locals } = getRequestEvent();
	if (locals.authEnabled) {
		const me = await fetchMe({
			catalogUrl: CATALOG_API,
			accessToken: locals.session?.accessToken,
			fetchFn: fetch,
		});
		if (!me?.estate_admin) error(403, 'the JetStream feed is estate-admin only');
	}
	if (!NATS_MONITOR_API) error(501, 'no NATS monitor is wired on this stack');

	let fingerprint = -1;
	let published = -1;
	let publishedAt = 0;
	for (;;) {
		try {
			const res = await fetch(`${NATS_MONITOR_API}/jsz`, {
				signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
			});
			if (res.ok) {
				const jsz = parse(JszProbeSchema, await res.json());
				// Totals only — the panel re-reads the trimmed, gated overview through its own BFF. Streams
				// and consumers ride along so a stream appearing or a consumer dying ticks even at a
				// standstill, which is the case this panel is for.
				fingerprint = jsz.messages * 1_000_000 + jsz.streams * 1000 + jsz.consumers;
			}
		} catch {
			/* fail quiet — the panel's own read renders the honest unavailable state */
		}
		const now = Date.now();
		if (fingerprint >= 0 && (fingerprint !== published || now - publishedAt >= KEEPALIVE_MS)) {
			published = fingerprint;
			publishedAt = now;
			yield fingerprint;
		}
		await sleep(POLL_MS);
	}
});

/** One run as the notification surface renders it — the `/runs` row minus everything a bell never shows. */
export interface RunNotice {
	run_id: string;
	job: string | null;
	/** Who ran it. Dropped from the first version of this trim, and the bell rendered "unknown author" on
	 *  every row — a field the surface displays is not an optional field. Caught by looking at the
	 *  screenshot (`docs/audits/shots/live-notification-bell.png`), not by any assertion. */
	author: string | null;
	state: string | null;
	progress_done: number | null;
	progress_total: number | null;
	error_message: string | null;
	updated_at: string | null;
	operation: string | null;
}

const RunsSchema = v.object({
	runs: v.array(
		v.object({
			run_id: v.string(),
			job: v.nullish(v.string()),
			author: v.nullish(v.string()),
			state: v.nullish(v.string()),
			progress_done: v.nullish(v.number()),
			progress_total: v.nullish(v.number()),
			error_message: v.nullish(v.string()),
			updated_at: v.nullish(v.string()),
			operation: v.nullish(v.string()),
		}),
	),
});

/** How many runs the bell keeps. A notification surface is a recency window, not the run board. */
const NOTICE_WINDOW = 20;

/** One beat of the lineage plane: where the estate's event log stands, and the runs behind the bell. */
export interface LineagePulse {
	/** The newest event `seq` this caller may see — the cursor every lineage-backed surface re-reads on. */
	cursor: number;
	/** The most recently active runs, trimmed to {@link NOTICE_WINDOW} on the server. */
	runs: RunNotice[];
}

/**
 * THE lineage feed — one stream carrying both the cursor and the notification runs, because the whole zone
 * needs exactly these two things and needs them to agree.
 *
 * It was two live queries at first: a cursor for the panels and a run feed for the shell's bell. Both are
 * mounted on every page (the bell lives in the root layout), so every page held two long-lived streams to
 * the same origin, each polling the same `/events` probe on its own clock. Measured against the e2e suite,
 * that peaked at ~30 probes/second — two per page, times pages whose server-side generator outlives the
 * closed page by a poll or two. Merging them halves that at a stroke, and it removes a subtler problem
 * for free: with separate cursors the bell and the table under it could be a poll apart on the same
 * estate, which is the exact complaint this whole change set exists to fix.
 *
 * `/runs` is the right backend for the notification half and needed nothing new — it folds each run's
 * lifecycle into a current state (START → RUNNING → COMPLETE/FAIL) with progress and error text, and it is
 * governed per subject (a run is shown only if the caller `can_get_metadata` on every dataset it wrote).
 * What did not exist was any surface at all.
 *
 * The runs are trimmed HERE, not in the browser: `/runs` measured 330_103 bytes on the live estate (875
 * runs), and a bell renders the newest {@link NOTICE_WINDOW} rows and the nine fields it displays. That is the
 * part of "server-side" that pays for itself.
 */
export const lineageFeed = query.live(async function* (): AsyncGenerator<LineagePulse> {
	const { fetch } = getRequestEvent();
	let cursor = -1;
	let sent = false;
	let sentAt = 0;

	async function read(): Promise<RunNotice[] | null> {
		try {
			const res = await fetch(`${LINEAGE_API}/runs`, {
				headers: lineageHeaders(),
				signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
			});
			if (!res.ok) return null;
			const board = parse(RunsSchema, await res.json());
			// FAILURES FIRST, then newest — and the order matters HERE, not only in the surface, because
			// this is where the list is CUT. Measured against the live estate: 891 runs with the first
			// FAIL at position 445, so a recency-only trim to 20 handed the bell twenty successes and the
			// panel could not have shown a failure however it sorted them. Fixing the component's ordering
			// alone changed nothing, which is what made the layering obvious.
			const failed = (r: { state?: string | null }) =>
				(r.state ?? '').toUpperCase() === 'FAIL' || (r.state ?? '').toUpperCase() === 'ABORT';
			return board.runs
				.slice()
				.sort((a, b) => {
					if (failed(a) !== failed(b)) return failed(a) ? -1 : 1;
					return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
				})
				.slice(0, NOTICE_WINDOW)
				.map((r) => ({
					run_id: r.run_id,
					job: r.job ?? null,
					author: r.author ?? null,
					state: r.state ?? null,
					progress_done: r.progress_done ?? null,
					progress_total: r.progress_total ?? null,
					error_message: r.error_message ?? null,
					updated_at: r.updated_at ?? null,
					operation: r.operation ?? null,
				}));
		} catch {
			return null;
		}
	}

	let last: RunNotice[] = [];
	for (;;) {
		const seq = await probeLineage();
		const moved = seq !== null && seq !== cursor;
		if (seq !== null) cursor = seq;
		const now = Date.now();
		// The run board is re-read only when the estate moved (or on the very first pass, so consumers
		// settle into an honest empty state instead of hanging in `pending`). Anything else is a
		// keepalive: it re-sends the LAST pulse so the stream is never severed as idle, and because
		// `cursor` is then an unchanged number, no panel's `$effect` re-runs on it.
		if (moved || !sent) {
			const runs = await read();
			if (runs !== null) last = runs;
			if (runs !== null || !sent) {
				sent = true;
				sentAt = now;
				yield { cursor: Math.max(cursor, 0), runs: last };
			}
		} else if (now - sentAt >= KEEPALIVE_MS) {
			sentAt = now;
			yield { cursor: Math.max(cursor, 0), runs: last };
		}
		await sleep(POLL_MS);
	}
});
