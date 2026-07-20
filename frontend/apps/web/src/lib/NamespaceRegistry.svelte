<script lang="ts">
	// `/namespaces` — the catalog's namespaces (#64 admin surface), grouped from the table registry
	// (`<namespace>$<table>`). There is no root-namespace list endpoint (the catalog's `list_namespaces`
	// needs a parent id), so we derive the namespaces from the tables the catalog lists: every namespace
	// that holds at least one table, with its tables linked into the detail view. Same stack-mode states
	// as the tables page — governed without a session ⇒ sign-in, unreachable ⇒ retrying, open ⇒ data.
	import { Boxes, RefreshCw, ShieldAlert } from "@lucide/svelte";
	import { fetchTables } from "./catalog";

	const POLL_MS = 5000;

	let tables = $state<string[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);

	const unauthorized = $derived(tables === null && lastStatus === 401);
	const offline = $derived(tables === null && settled && lastStatus !== 401);

	// Group by the namespace segment (before the first `$`); a bare name with no delimiter is its own root.
	const groups = $derived.by(() => {
		const m = new Map<string, string[]>();
		for (const t of tables ?? []) {
			const ns = t.includes("$") ? t.slice(0, t.indexOf("$")) : t;
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
</script>

<div class="page">
	<header>
		<h1>Namespaces</h1>
		<span class="sub mono">grouped from the catalog registry · &lt;namespace&gt;$&lt;table&gt;</span
		>
	</header>

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
		<div class="empty"><p>No namespaces yet — a table create makes the first.</p></div>
	{:else}
		{#each groups as [ns, members] (ns)}
			<section class="ns">
				<div class="ns-head">
					<Boxes size={13} />
					<span class="mono ns-name">{ns}</span>
					<span class="count">{members.length} table{members.length === 1 ? "" : "s"}</span>
				</div>
				<ul class="list">
					{#each members as t (t)}
						<li><a class="row mono" href={`/tables/${encodeURIComponent(t)}`}>{t}</a></li>
					{/each}
				</ul>
			</section>
		{/each}
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
</style>
