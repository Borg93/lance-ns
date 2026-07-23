<script lang="ts">
	// `/streams` — read-only JetStream visibility over the estate's event fabric. The /api/jetstream BFF
	// admin-gates (medallion /authorize), fetches the unauthenticated NATS monitor `/jsz` server-side, and
	// returns a trimmed typed overview — the monitor URL and raw payload never reach the browser. This panel
	// renders stream cards with per-consumer lag (pending / ack-pending / redelivered): redeliveries are the
	// wedge signal, backlog the pressure signal. Strictly a viewer — no mutation affordances by design.
	import { Layers, RefreshCw, ShieldAlert } from '@lucide/svelte';
	import { parse } from '@rask/api';
	import { JetStreamOverviewSchema, type JetStreamOverview } from './jetstream';
	import { requestJSON } from './http';

	let overview = $state<JetStreamOverview | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let inflight = 0;

	const unauthorized = $derived(overview === null && settled && lastStatus === 401);
	const forbidden = $derived(overview === null && settled && lastStatus === 403);
	const unavailable = $derived(overview === null && settled && lastStatus === 501);
	// -1 = the client-side parse boundary rejected the BFF payload (contract drift, not a monitor outage).
	const drifted = $derived(overview === null && settled && lastStatus === -1);
	// 0 stays IN the offline set: after the first settle, a fetch-level failure (network down, BFF timeout)
	// reports status 0 and must render as offline, not hang on the loading message (audit finding).
	const offline = $derived(
		overview === null && settled && ![-1, 200, 401, 403, 501].includes(lastStatus),
	);

	async function load(): Promise<void> {
		const seq = ++inflight;
		const res = await requestJSON<unknown>('/api', 'jetstream');
		if (seq !== inflight) return; // latest-wins
		settled = true;
		if (res.ok) {
			try {
				// Wire boundary: parse (don't cast) the trimmed shape, so a BFF/schema drift surfaces as an
				// honest unreachable state instead of a UI built from values that lie about their type.
				overview = parse(JetStreamOverviewSchema, res.data);
				lastStatus = 200;
			} catch (err) {
				// -1 = contract drift (the drifted state), distinct from a monitor outage's 502 (audit nit).
				console.error(`jetstream overview parse failure: ${String(err)}`);
				overview = null;
				lastStatus = -1;
			}
		} else {
			// Clear the stale view on failure so the auth/forbidden/offline state reflects reality — else a
			// session that expires mid-view would keep showing the old (privileged) topology.
			overview = null;
			lastStatus = res.status;
		}
	}

	$effect(() => {
		load();
	});

	// The lineage transactional-outbox DLQ stream (#83) — visually flagged so an operator scanning the
	// fabric spots dead-letter backlog at a glance.
	const isDlq = (name: string) => name === 'DLQ' || name.startsWith('DLQ_');

	function fmtBytes(n: number): string {
		if (n < 1024) return `${n} B`;
		if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KiB`;
		if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MiB`;
		return `${(n / 1024 ** 3).toFixed(1)} GiB`;
	}
	/** int64 nanoseconds → compact duration; 0 means unlimited in JetStream configs. */
	function fmtAgeNs(ns: number): string {
		if (ns <= 0) return '∞';
		const s = ns / 1e9;
		if (s < 60) return `${Math.round(s)}s`;
		if (s < 3600) return `${Math.round(s / 60)}m`;
		if (s < 86400) return `${Math.round(s / 3600)}h`;
		return `${Math.round(s / 86400)}d`;
	}
	function when(ts: string | undefined): string {
		if (!ts) return '—';
		const d = new Date(ts);
		return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
	}
</script>

<div class="page">
	<header>
		<Layers size={16} />
		<h1>Streams</h1>
		<span class="sub mono">JetStream streams · consumer lag · read-only from the NATS monitor</span>
	</header>

	<div class="bar">
		<button class="btn" onclick={load}><RefreshCw size={13} /> Refresh</button>
		{#if overview}
			<span class="totals mono">
				{overview.totals.streams} streams · {overview.totals.consumers} consumers ·
				{overview.totals.messages.toLocaleString()} msgs · {fmtBytes(overview.totals.bytes)}
			</span>
		{/if}
	</div>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={15} /> <a href="/auth/login">Sign in</a> to view JetStream streams.
		</div>
	{:else if forbidden}
		<div class="empty">
			<ShieldAlert size={15} /> The stream view is admin-only — your account isn't a project admin.
		</div>
	{:else if unavailable}
		<div class="empty">The stream view needs the NATS monitor (NATS_MONITOR_API unset).</div>
	{:else if drifted}
		<div class="empty">
			<ShieldAlert size={15} /> The overview payload drifted from the contract — refusing to render it.
		</div>
	{:else if offline}
		<div class="empty"><RefreshCw size={15} /> NATS monitor unreachable (HTTP {lastStatus}).</div>
	{:else if overview === null}
		<div class="empty">Loading the JetStream overview…</div>
	{:else if overview.streams.length === 0}
		<div class="empty">No JetStream streams exist yet — the event fabric is empty.</div>
	{:else}
		<div class="cards">
			{#each overview.streams as s (s.name)}
				<section class="card" class:dlq={isDlq(s.name)} aria-label="Stream {s.name}">
					<div class="card-head">
						<span class="name mono">{s.name}</span>
						{#if isDlq(s.name)}
							<span
								class="badge dlqbadge"
								title="Lineage dead-letter stream — backlog here is at-risk events"
							>
								DLQ
							</span>
						{/if}
						<span class="badge">{s.retention}</span>
						<span class="badge">{s.storage}</span>
						<span class="spacer"></span>
						<span class="stat mono">
							{s.state.messages.toLocaleString()} msgs · {fmtBytes(s.state.bytes)} · seq
							{s.state.first_seq}–{s.state.last_seq} · max_age {fmtAgeNs(s.max_age_ns)} · R{s.num_replicas}
						</span>
					</div>
					<div class="subjects mono">{s.subjects.join(', ') || '—'}</div>
					{#if s.consumers.length === 0}
						<div class="noconsumers">No consumers bound ({s.state.consumer_count} reported).</div>
					{:else}
						<table>
							<thead>
								<tr>
									<th>consumer</th><th>group</th><th class="num">pending</th>
									<th class="num">ack-pending</th><th class="num">redelivered</th><th
										>last active</th
									>
								</tr>
							</thead>
							<tbody>
								{#each s.consumers as c (c.name)}
									<tr>
										<td class="mono">
											{c.durable ? c.name : `${c.name} (ephemeral)`}
										</td>
										<td class="mono">{c.deliver_group ?? '—'}</td>
										<td class="num mono" class:pend={c.num_pending > 0}>{c.num_pending}</td>
										<td class="num mono" class:pend={c.num_ack_pending > 0}>{c.num_ack_pending}</td>
										<td class="num mono" class:warn={c.num_redelivered > 0}>{c.num_redelivered}</td>
										<td class="mono faint">{when(c.last_active)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</section>
			{/each}
		</div>
	{/if}
</div>

<style>
	.page {
		max-width: 980px;
		margin: 0 auto;
		padding: 56px 20px 40px;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 16px;
	}
	h1 {
		font-size: 20px;
		margin: 0;
	}
	.sub {
		color: var(--faint);
		font-size: 12px;
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 14px;
		flex-wrap: wrap;
	}
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 12px;
		cursor: pointer;
	}
	.totals {
		font-size: 12px;
		color: var(--mut);
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		font-size: 13px;
		padding: 30px 0;
	}
	.cards {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.card {
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: var(--panel-2);
		padding: 12px 14px;
	}
	.card.dlq {
		border-color: color-mix(in srgb, var(--warn, #d18b28) 55%, var(--line));
	}
	.card-head {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.name {
		font-size: 13px;
		font-weight: 600;
		color: var(--ink);
	}
	.badge {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--mut);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		padding: 1px 6px;
	}
	.badge.dlqbadge {
		color: var(--warn, #d18b28);
		border-color: color-mix(in srgb, var(--warn, #d18b28) 60%, var(--line));
	}
	.spacer {
		flex: 1;
	}
	.stat {
		font-size: 11px;
		color: var(--faint);
	}
	.subjects {
		font-size: 11px;
		color: var(--mut);
		margin: 6px 0 8px;
	}
	.noconsumers {
		font-size: 12px;
		color: var(--faint);
		padding: 4px 0;
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
	}
	th {
		text-align: left;
		color: var(--faint);
		font-weight: 500;
		padding: 4px 14px 4px 0;
		border-bottom: 1px solid var(--line);
	}
	td {
		padding: 4px 14px 4px 0;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
	}
	tr:last-child td {
		border-bottom: none;
	}
	th.num,
	td.num {
		text-align: right;
	}
	td.num {
		color: var(--faint);
	}
	td.pend {
		color: var(--mut);
	}
	td.warn {
		color: var(--warn, #d18b28);
	}
	.faint {
		color: var(--faint);
		white-space: nowrap;
	}
</style>
