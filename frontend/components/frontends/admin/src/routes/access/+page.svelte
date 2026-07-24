<script lang="ts">
	// `/admin/access` — the estate access-review surface (goal cond 3): pick any catalog object
	// (table or namespace) and host the shared GrantsPanel on it — the #51 review, the #68
	// "who-can-do-what" check playground, and the #72 grant/revoke entries, all owner-gated BY THE
	// CATALOG through this zone's narrow session-only pass-through. The registry list below offers
	// tables as one-click entry points; namespaces are derived from the same ids.
	import { GrantsPanel, type GrantsKind } from '@rask/ui/grants-panel';
	import { Select } from '@rask/ui/select';
	import { ShieldCheck } from '@lucide/svelte';
	import { accessClient, fetchTables } from '$lib/access';

	let kind = $state<string>('table');
	let objectId = $state('');
	// The LOADED target (kind + id frozen on Load), so typing doesn't re-key the panel mid-review.
	let target = $state<{ kind: GrantsKind; id: string } | null>(null);

	let tables = $state<string[] | null>(null);
	let registryStatus = $state(0);

	async function loadRegistry(): Promise<void> {
		const res = await fetchTables();
		if (res.ok) {
			tables = [...res.data.tables].sort();
			registryStatus = 200;
		} else {
			tables = null;
			registryStatus = res.status;
		}
	}

	$effect(() => {
		loadRegistry();
	});

	// Namespaces derived from the registry ids (the segment before the first `$`).
	const namespaces = $derived(
		[
			...new Set((tables ?? []).map((t) => (t.includes('$') ? t.slice(0, t.indexOf('$')) : t))),
		].sort(),
	);

	function open(k: GrantsKind, id: string): void {
		kind = k;
		objectId = id;
		target = { kind: k, id };
	}

	function load(): void {
		const id = objectId.trim();
		if (!id) return;
		target = { kind: kind as GrantsKind, id };
	}
</script>

<svelte:head><title>Access · lance</title></svelte:head>

<div class="page">
	<header>
		<ShieldCheck size={16} />
		<h1>Access</h1>
		<span class="sub mono"
			>estate access review · who-can-do-what playground · grants (#51/#68/#72)</span
		>
	</header>

	<form
		class="picker"
		onsubmit={(e) => {
			e.preventDefault();
			load();
		}}
	>
		<Select
			bind:value={kind}
			ariaLabel="Object kind"
			options={[
				{ value: 'table', label: 'table' },
				{ value: 'namespace', label: 'namespace' },
			]}
		/>
		<input
			class="mono"
			bind:value={objectId}
			placeholder={kind === 'table' ? 'namespace$table' : 'namespace'}
			aria-label="Object id"
		/>
		<button class="btn" type="submit" disabled={!objectId.trim()}>Load</button>
	</form>

	{#if target}
		<section class="panel">
			<h2 class="mono">{target.kind}:{target.id}</h2>
			{#key `${target.kind}:${target.id}`}
				<GrantsPanel dataset={target.id} kind={target.kind} client={accessClient} />
			{/key}
		</section>
	{/if}

	<section>
		<h2>Registry entries</h2>
		{#if tables === null}
			<p class="mut">
				{registryStatus === 0
					? 'Loading the registry…'
					: `Registry unavailable (HTTP ${registryStatus}) — enter an object id above.`}
			</p>
		{:else if tables.length === 0}
			<p class="mut">No tables registered yet.</p>
		{:else}
			<div class="entries">
				{#each namespaces as ns (ns)}
					<button class="chip mono" onclick={() => open('namespace', ns)}>ns · {ns}</button>
				{/each}
				{#each tables as t (t)}
					<button class="chip mono" onclick={() => open('table', t)}>{t}</button>
				{/each}
			</div>
		{/if}
	</section>
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
	.picker {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 18px;
	}
	.picker input {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 8px;
		flex: 1 1 220px;
	}
	.btn {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 14px;
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.panel {
		margin-bottom: 22px;
	}
	section h2 {
		font-size: 13px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--faint);
		margin: 0 0 8px;
	}
	.panel h2 {
		text-transform: none;
		letter-spacing: 0;
		color: var(--ink);
		font-size: 14px;
	}
	.mut {
		color: var(--faint);
		font-size: 12px;
	}
	.entries {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		color: var(--mut);
		font-size: 12px;
		padding: 1px 10px;
		cursor: pointer;
	}
	.chip:hover {
		color: var(--ink);
		border-color: var(--mut);
	}
	.mono {
		font-family: ui-monospace, monospace;
	}
</style>
