<script lang="ts">
	// `/dlq` — the #83 lineage DLQ / transactional-outbox ops panel. The outbox holds events staged before
	// publish and dropped on ack; a surviving object is a committed write whose lineage was not yet confirmed
	// delivered — the at-risk set the reconcile relay drains on a timer. This panel surfaces that set and lets
	// an operator replay one on demand (re-ingest + drop) instead of waiting for the next tick. The list is
	// governed per-dataset by the service; replay forwards the signed-in user's bearer through a session-only
	// BFF route (never the service token). Governed without a session → 401.
	import { RefreshCw, RotateCcw, ShieldAlert, Inbox } from '@lucide/svelte';
	import { page } from '$app/state';
	import { fetchDlq, replayDlq } from './api';
	import type { DlqBacklog, DlqEvent } from './types';

	// Return here after the OIDC round-trip (the shell's ?redirect= contract, nav-user.svelte).
	const loginHref = $derived(`/auth/login?redirect=${encodeURIComponent(page.url.pathname)}`);

	let backlog = $state<DlqBacklog | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let inflight = 0;
	let busy = $state<string | null>(null); // run_id currently replaying
	let msg = $state<{ ok: boolean; text: string } | null>(null);

	const unauthorized = $derived(backlog === null && settled && lastStatus === 401);
	// 0 stays IN the offline set: after the first settle, a fetch-level failure (network down, BFF timeout)
	// reports status 0 and must render as offline, not hang on the loading message (audit finding).
	const offline = $derived(backlog === null && settled && ![200, 401].includes(lastStatus));

	async function load(): Promise<void> {
		const seq = ++inflight;
		const res = await fetchDlq(200);
		if (seq !== inflight) return; // latest-wins
		settled = true;
		if (res.ok) {
			backlog = res.data;
			lastStatus = 200;
		} else {
			// Clear the stale view on failure so the auth/offline state reflects reality — else a session that
			// expires after a first successful load would keep showing the old event table (the derivations
			// gate on backlog === null) instead of the sign-in prompt. (audit 2026-07-20)
			backlog = null;
			lastStatus = res.status;
		}
	}

	async function replay(e: DlqEvent): Promise<void> {
		if (busy) return;
		busy = e.run_id;
		msg = null;
		try {
			const res = await replayDlq(e.run_id);
			if (res.ok) {
				msg = { ok: true, text: `Replayed ${e.run_id}.` };
				await load();
			} else if (res.status === 401) {
				msg = { ok: false, text: 'Sign in to replay a lineage event.' };
			} else if (res.status === 403) {
				msg = { ok: false, text: "Denied: replay needs writer access on the event's outputs." };
			} else {
				msg = { ok: false, text: res.detail };
			}
		} finally {
			busy = null;
		}
	}

	$effect(() => {
		load();
	});

	function age(seconds: number): string {
		if (seconds < 60) return `${Math.round(seconds)}s`;
		if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
		if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
		return `${Math.round(seconds / 86400)}d`;
	}
</script>

<div class="page">
	<header>
		<Inbox size={16} />
		<h1>Lineage DLQ</h1>
		<span class="sub mono">transactional-outbox at-risk events · view + replay (#83)</span>
	</header>

	<div class="bar">
		<button class="btn" onclick={load}><RefreshCw size={13} /> Refresh</button>
		{#if backlog}
			<span class="depth mono" class:warn={backlog.depth > 0}>
				depth {backlog.depth}{backlog.depth > 0
					? ` · oldest ${age(backlog.oldest_age_seconds)}`
					: ''}
			</span>
		{/if}
		{#if msg}<span class="msg" class:okmsg={msg.ok} class:error={!msg.ok}>{msg.text}</span>{/if}
	</div>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={15} /> <a href={loginHref} data-sveltekit-reload>Sign in</a> to view the lineage
			DLQ.
		</div>
	{:else if offline}
		<div class="empty"><RefreshCw size={15} /> DLQ store unreachable (HTTP {lastStatus}).</div>
	{:else if backlog === null}
		<div class="empty">Loading the outbox backlog…</div>
	{:else if backlog.events.length === 0}
		<div class="empty">
			The outbox is empty — every committed write's lineage has been delivered. Nothing to replay.
		</div>
	{:else}
		<table>
			<thead
				><tr><th>run</th><th>type</th><th>job</th><th>outputs</th><th>inputs</th><th></th></tr
				></thead
			>
			<tbody>
				{#each backlog.events as e (e.run_id)}
					<tr class:poison={!e.parseable}>
						<td class="mono run">{e.run_id}</td>
						<td class="mono">{e.parseable ? (e.event_type ?? '—') : 'poison'}</td>
						<td class="mono">{e.job ?? '—'}</td>
						<td class="mono">{(e.outputs ?? []).join(', ') || '—'}</td>
						<td class="mono">{(e.inputs ?? []).join(', ') || '—'}</td>
						<td class="actions">
							{#if e.parseable}
								<button
									class="btn ghost"
									disabled={busy !== null}
									aria-label="Replay {e.run_id}"
									onclick={() => replay(e)}
									><RotateCcw size={12} /> {busy === e.run_id ? '…' : 'Replay'}</button
								>
							{:else}
								<span
									class="mut"
									title="An unparseable object can't be replayed; the relay drops it."
									>unreplayable</span
								>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
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
	.btn.ghost {
		padding: 2px 8px;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.depth {
		font-size: 12px;
		color: var(--mut);
	}
	.depth.warn {
		color: var(--warn, #d18b28);
	}
	.msg {
		font-size: 12px;
	}
	.okmsg {
		color: var(--ok);
	}
	.error {
		color: var(--fail);
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		font-size: 13px;
		padding: 30px 0;
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
	.run {
		color: var(--faint);
		white-space: nowrap;
	}
	tr.poison td {
		color: var(--fail);
	}
	.mut {
		color: var(--faint);
	}
	.actions {
		text-align: right;
	}
</style>
