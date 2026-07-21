<script lang="ts">
	// `/tables` — the catalog table registry (#52): every table the catalog's own backend lists,
	// linking into the detail view. Same stack-mode states as the models page: governed without a
	// session ⇒ sign-in, unreachable ⇒ retrying, open ⇒ data or the honest empty state.
	import { base } from '$app/paths';
	import { RefreshCw, ShieldAlert } from '@lucide/svelte';
	import { fetchTables } from './catalog';

	const POLL_MS = 5000;

	let tables = $state<string[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false); // distinguishes "still loading" (0, unsettled) from a network error (0, settled)

	const unauthorized = $derived(tables === null && lastStatus === 401);
	const offline = $derived(tables === null && settled && lastStatus !== 401);

	async function load(): Promise<void> {
		const res = await fetchTables();
		settled = true;
		if (res.ok) {
			// A copy + sort, not toSorted() — the latter is ES2023, above the repo's Safari-16 floor.
			tables = [...res.data.tables].sort();
			lastStatus = 200;
		} else {
			lastStatus = res.status; // status 0 (offline/timeout) now reads as offline, not a stuck spinner
		}
	}

	$effect(() => {
		load();
		const timer = setInterval(load, POLL_MS); // a transient failure retries, so "retrying" is honest
		return () => clearInterval(timer);
	});
</script>

<div class="page">
	<header>
		<h1>Tables</h1>
		<span class="sub mono">the catalog registry · &lt;namespace&gt;$&lt;table&gt;</span>
	</header>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={16} />
			<p>This stack is governed — <a href="/auth/login">sign in</a> to browse the catalog.</p>
		</div>
	{:else if offline}
		<div class="empty">
			<RefreshCw size={16} />
			<p>Catalog unreachable (HTTP {lastStatus}) — retrying.</p>
		</div>
	{:else if tables === null}
		<div class="empty"><p>Loading…</p></div>
	{:else if tables.length === 0}
		<div class="empty">
			<p>No tables registered — a create (or the medallion cascade's gold sink) makes the first.</p>
		</div>
	{:else}
		<ul class="list">
			{#each tables as t (t)}
				<li><a class="row mono" href={`${base}/tables/${encodeURIComponent(t)}`}>{t}</a></li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.page {
		max-width: 860px;
		margin: 0 auto;
		padding: 56px 20px 40px;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 18px;
	}
	h1 {
		font-size: 20px;
		margin: 0;
	}
	.sub {
		color: var(--faint);
		font-size: 12px;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.row {
		display: block;
		padding: 7px 10px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
		color: var(--ink);
		text-decoration: none;
		font-size: 13px;
	}
	.row:hover {
		background: var(--panel-2);
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		padding: 32px 0;
	}
</style>
