<script lang="ts">
	// `/namespaces` — the catalog's namespaces (#64 admin surface), grouped from the table registry
	// (`<namespace>$<table>`). There is no root-namespace list endpoint (the catalog's `list_namespaces`
	// needs a parent id), so we derive the namespaces from the tables the catalog lists: every namespace
	// that holds at least one table, with its tables linked into the detail view. Same stack-mode states
	// as the tables page — governed without a session ⇒ sign-in, unreachable ⇒ retrying, open ⇒ data.
	// Lifecycle (#85): drop with an AlertDialog confirm (Restrict by default; Cascade opt-in — the
	// catalog's dir backend errors a Restrict drop of a non-empty namespace). Creation deliberately has
	// NO surface here — the governed path is the warehouse-bind flow (/warehouses), which the "New
	// namespace" affordance points at; a bare create would bypass the bucket-per-warehouse tenancy.
	import { AlertDialog } from '@rask/ui/alert-dialog';
	import { Boxes, Plus, RefreshCw, ShieldAlert, Trash2 } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { dropNamespace, fetchTables } from './catalog';

	const POLL_MS = 5000;

	let tables = $state<string[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let busy = $state(false);
	let banner = $state<{ tone: 'ok' | 'fail'; text: string } | null>(null);
	let dropOpen = $state(false);
	let dropTarget = $state<string | null>(null);
	let cascade = $state(false);

	const unauthorized = $derived(tables === null && lastStatus === 401);
	const offline = $derived(tables === null && settled && lastStatus !== 401);

	// Group by the namespace segment (before the first `$`); a bare name with no delimiter is its own root.
	const groups = $derived.by(() => {
		const m = new Map<string, string[]>();
		for (const t of tables ?? []) {
			const ns = t.includes('$') ? t.slice(0, t.indexOf('$')) : t;
			const arr = m.get(ns);
			if (arr) arr.push(t);
			else m.set(ns, [t]);
		}
		return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
	});

	async function load(): Promise<void> {
		const res = await fetchTables();
		settled = true;
		if (res.ok) {
			tables = [...res.data.tables].sort();
			lastStatus = 200;
		} else {
			lastStatus = res.status;
		}
	}

	$effect(() => {
		load();
		const timer = setInterval(load, POLL_MS);
		return () => clearInterval(timer);
	});

	// Tables inside the namespace queued for drop — sizes the Cascade choice honestly.
	const targetCount = $derived(
		dropTarget === null ? 0 : (groups.find(([ns]) => ns === dropTarget)?.[1].length ?? 0),
	);

	function openDrop(ns: string): void {
		dropTarget = ns;
		cascade = false;
		banner = null;
		dropOpen = true;
	}

	function fail(ns: string, status: number, detail: string): void {
		if (status === 401)
			banner = { tone: 'fail', text: 'Sign in — dropping a namespace is a per-user action.' };
		else if (status === 403)
			banner = { tone: 'fail', text: `Denied: dropping ${ns} needs the owner rung (can_delete).` };
		else if (status === 0)
			banner = { tone: 'fail', text: 'Catalog unreachable — the drop was not applied.' };
		else banner = { tone: 'fail', text: detail };
	}

	async function confirmDrop(): Promise<void> {
		const ns = dropTarget;
		if (ns === null || busy) return;
		busy = true;
		banner = null;
		try {
			const res = await dropNamespace(ns, cascade);
			if (res.ok) {
				banner = { tone: 'ok', text: `namespace ${ns} dropped${cascade ? ' (cascade)' : ''}` };
				await load();
			} else {
				fail(ns, res.status, res.detail);
			}
		} catch (err) {
			// the parse boundary throws on a wire-contract drift — surface it, never render from a lie
			banner = { tone: 'fail', text: `drop response drifted from the contract: ${String(err)}` };
		} finally {
			// ALWAYS close + disarm: bits-ui's AlertDialog.Action does not auto-close, so leaving the dialog
			// open would keep the destructive action armed for a second, confirm-free fire (audit: major).
			// The banner carries success/failure either way.
			busy = false;
			dropOpen = false;
			dropTarget = null;
		}
	}
</script>

<div class="page">
	<header>
		<h1>Namespaces</h1>
		<span class="sub mono">grouped from the catalog registry · &lt;namespace&gt;$&lt;table&gt;</span
		>
		<a
			class="new"
			href={`${base}/warehouses`}
			title="Namespaces are created through the governed warehouse-bind flow"
		>
			<Plus size={12} /> New namespace
		</a>
	</header>

	{#if banner}
		<div class="banner" class:ok={banner.tone === 'ok'} class:fail={banner.tone === 'fail'}>
			{banner.text}
		</div>
	{/if}

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={16} />
			<p>This stack is governed — <a href="/auth/login">sign in</a> to browse namespaces.</p>
		</div>
	{:else if offline}
		<div class="empty">
			<RefreshCw size={16} />
			<p>Catalog unreachable (HTTP {lastStatus}) — retrying.</p>
		</div>
	{:else if tables === null}
		<div class="empty"><p>Loading…</p></div>
	{:else if groups.length === 0}
		<div class="empty">
			<p>
				No namespaces yet — <a href={`${base}/warehouses`}>bind one to a warehouse</a> to create the first.
			</p>
		</div>
	{:else}
		{#each groups as [ns, members] (ns)}
			<section class="ns">
				<div class="ns-head">
					<Boxes size={13} />
					<a class="mono ns-name" href={`${base}/namespaces/${encodeURIComponent(ns)}`}>{ns}</a>
					<span class="count">{members.length} table{members.length === 1 ? '' : 's'}</span>
					<button
						class="drop"
						aria-label={`Drop namespace ${ns}`}
						disabled={busy}
						onclick={() => openDrop(ns)}
					>
						<Trash2 size={12} /> drop
					</button>
				</div>
				<ul class="list">
					{#each members as t (t)}
						<li><a class="row mono" href={`${base}/tables/${encodeURIComponent(t)}`}>{t}</a></li>
					{/each}
				</ul>
			</section>
		{/each}
	{/if}
</div>

<AlertDialog.Root bind:open={dropOpen}>
	<AlertDialog.Content>
		<AlertDialog.Title>Drop namespace {dropTarget}</AlertDialog.Title>
		<AlertDialog.Description>
			This permanently drops <span class="mono">{dropTarget}</span> from the catalog (owner-gated: can_delete).
			The default Restrict behavior refuses a non-empty namespace — tick Cascade to also drop everything
			inside it.
		</AlertDialog.Description>
		<label class="cascade">
			<input type="checkbox" bind:checked={cascade} disabled={busy} />
			Cascade — also drop the {targetCount} table{targetCount === 1 ? '' : 's'} inside
		</label>
		<div class="dialog-actions">
			<AlertDialog.Cancel disabled={busy}>Cancel</AlertDialog.Cancel>
			<AlertDialog.Action
				class="border-destructive/40 bg-destructive/15 text-destructive hover:bg-destructive/25"
				disabled={busy}
				onclick={confirmDrop}
			>
				Drop
			</AlertDialog.Action>
		</div>
	</AlertDialog.Content>
</AlertDialog.Root>

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
		text-decoration: none;
	}
	.new:hover {
		border-color: var(--mut);
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
	.ns {
		margin-bottom: 18px;
	}
	.ns-head {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 4px;
		color: var(--mut);
	}
	.ns-name {
		font-size: 13px;
		color: var(--ink);
	}
	.count {
		font-size: 11px;
		color: var(--faint);
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0 0 0 20px;
	}
	.row {
		display: block;
		padding: 6px 10px;
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
	.drop {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin-left: auto;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--faint);
		font-size: 11px;
		padding: 2px 6px;
		cursor: pointer;
	}
	.drop:hover {
		color: var(--fail);
		background: var(--panel-2);
	}
	.drop:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.cascade {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		font-size: 13px;
	}
	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
