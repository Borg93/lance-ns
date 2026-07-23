<script lang="ts">
	// `/tables` — the catalog table registry (#52): every table the catalog's own backend lists,
	// linking into the detail view. Same stack-mode states as the models page: governed without a
	// session ⇒ sign-in, unreachable ⇒ retrying, open ⇒ data or the honest empty state.
	// #85: the "Declare table" form is the browser-shaped create — declare_table takes a JSON body
	// (no Arrow payload), reserves the id, and seeds the caller's ownership; location left empty lets
	// the catalog pick. Gated can_create_table on the parent namespace (session-only BFF).
	import { base } from '$app/paths';
	import { Plus, RefreshCw, ShieldAlert } from '@lucide/svelte';
	import { declareTable, fetchTables } from './catalog';

	const POLL_MS = 5000;

	let tables = $state<string[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false); // distinguishes "still loading" (0, unsettled) from a network error (0, settled)

	const unauthorized = $derived(tables === null && lastStatus === 401);
	const offline = $derived(tables === null && settled && lastStatus !== 401);

	// #85 declare-table form state — hidden behind a toggle so the registry stays a list by default.
	let declaring = $state(false);
	let declNs = $state('');
	let declName = $state('');
	let declLocation = $state(''); // optional — empty means the catalog picks the location
	let declBusy = $state(false);
	let declMsg = $state<{ ok: boolean; text: string } | null>(null);

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

	async function runDeclare(): Promise<void> {
		const ns = declNs.trim();
		const name = declName.trim();
		if (declBusy || !ns || !name) return;
		declBusy = true;
		declMsg = null;
		try {
			const res = await declareTable(ns, name, declLocation.trim() || undefined);
			if (res.ok) {
				declMsg = {
					ok: true,
					text: `declared ${ns}$${name}${res.data.location ? ` @ ${res.data.location}` : ''}`,
				};
				declNs = '';
				declName = '';
				declLocation = '';
				await load(); // pull the declared table into the registry
			} else if (res.status === 401) {
				declMsg = { ok: false, text: 'Sign in to declare a table.' };
			} else if (res.status === 403) {
				declMsg = {
					ok: false,
					text: `Denied: declaring in ${ns} needs create access (can_create_table).`,
				};
			} else if (res.status === 0) {
				declMsg = { ok: false, text: 'Catalog unreachable — the declare was not applied.' };
			} else {
				declMsg = { ok: false, text: res.detail };
			}
		} catch (err) {
			// the parse boundary throws on a wire-contract drift — surface it, never render from a lie
			declMsg = { ok: false, text: `declare response drifted from the contract: ${String(err)}` };
		} finally {
			declBusy = false;
		}
	}
</script>

<div class="page">
	<header>
		<h1>Tables</h1>
		<span class="sub mono">the catalog registry · &lt;namespace&gt;$&lt;table&gt;</span>
		{#if !unauthorized}
			<button class="new" onclick={() => (declaring = !declaring)}>
				<Plus size={12} /> Declare table
			</button>
		{/if}
	</header>

	{#if declaring && !unauthorized}
		<!-- #85 the browser-shaped create: declare an empty table (JSON, no Arrow). -->
		<form
			class="declare"
			onsubmit={(e) => {
				e.preventDefault();
				runDeclare();
			}}
		>
			<input class="mono" bind:value={declNs} placeholder="namespace" aria-label="Namespace" />
			<input class="mono" bind:value={declName} placeholder="table name" aria-label="Table name" />
			<input
				class="mono loc"
				bind:value={declLocation}
				placeholder="location (optional — catalog picks)"
				aria-label="Location"
			/>
			<button class="btn" type="submit" disabled={declBusy || !declNs.trim() || !declName.trim()}>
				{declBusy ? '…' : 'Declare'}
			</button>
		</form>
	{/if}
	{#if declMsg}
		<div class="banner" class:ok={declMsg.ok} class:fail={!declMsg.ok}>{declMsg.text}</div>
	{/if}

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
	.new {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		margin-left: auto;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 12px;
		cursor: pointer;
	}
	.new:hover {
		border-color: var(--mut);
	}
	.declare {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 12px;
	}
	.declare input {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 8px;
	}
	.declare .loc {
		flex: 1;
		min-width: 220px;
	}
	.btn {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 3px 10px;
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.banner {
		padding: 8px 12px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--line);
		margin-bottom: 12px;
		font-size: 13px;
	}
	.banner.ok {
		border-color: color-mix(in srgb, var(--ok) 45%, var(--line));
		color: var(--ok);
	}
	.banner.fail {
		border-color: color-mix(in srgb, var(--fail) 45%, var(--line));
		color: var(--fail);
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
