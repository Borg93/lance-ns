<script lang="ts">
	import { SvelteFlow, Background, BackgroundVariant, Controls, MiniMap } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { Tabs } from 'bits-ui';
	import MedallionNode, { type MedallionNodeType } from '$lib/MedallionNode.svelte';
	import { LineageState } from '$lib/store.svelte';
	import { LAYER } from '$lib/types';

	const store = new LineageState();
	const nodeTypes = { medallion: MedallionNode };

	let nodes = $state.raw<MedallionNodeType[]>([]);
	let edges = $state.raw<{ id: string; source: string; target: string; animated: boolean; type: string }[]>([]);

	// Poll the lineage service every 2s.
	$effect(() => {
		store.poll();
		const timer = setInterval(() => store.poll(), 2000);
		return () => clearInterval(timer);
	});

	// Rebuild the flow graph whenever the polled data changes (deterministic layer layout).
	$effect(() => {
		nodes = store.nodes.map((n) => {
			const runs = store.producers[n.id] ?? [];
			const versions = [...new Set(runs.map((r) => r.dataset_version).filter(Boolean) as string[])].sort();
			const failed = runs.some((r) => /FAIL|ABORT/i.test(r.event_type ?? ''));
			const layer = LAYER[n.id] ?? 4;
			return {
				id: n.id,
				type: 'medallion' as const,
				position: { x: 30 + layer * 300, y: 150 },
				data: {
					id: n.id,
					layer,
					source_uri: n.source_uri,
					tags: n.tags,
					versions,
					failed,
					selected: store.selected === n.id
				}
			};
		});
		edges = store.edges.map((e) => ({
			id: `${e.target}->${e.source}`,
			source: e.target,
			target: e.source,
			animated: true,
			type: 'smoothstep'
		}));
	});

	function selectNode(e: unknown) {
		const ev = e as { node?: { id: string }; targetNode?: { id: string } };
		store.selected = ev.node?.id ?? ev.targetNode?.id ?? null;
	}

	const stateColor = (s?: string | null) =>
		/FAIL|ABORT/i.test(s ?? '') ? 'var(--fail)' : s === 'COMPLETE' ? 'var(--ok)' : 'var(--mut)';

	const selectedRuns = $derived(store.selected ? (store.producers[store.selected] ?? []) : []);
</script>

<div class="app">
	<header>
		<h1>Lance Lineage <span class="sub">live medallion — OpenLineage → Apache AGE → real Lance on S3</span></h1>
		<div class="legend">
			<span><i style="background:#ff9457"></i>raw</span>
			<span><i style="background:#cd7f32"></i>bronze</span>
			<span><i style="background:#9fb6cf"></i>silver</span>
			<span><i style="background:#ffc14d"></i>gold</span>
		</div>
		<div class="status">
			<span class="dot" class:on={store.online}></span>
			{store.online ? 'live' : 'waiting'} · {store.nodes.length} datasets · {store.events.length} events
			{#if store.lastUpdated}· {store.lastUpdated}{/if}
		</div>
	</header>

	<main>
		<section class="graph">
			<SvelteFlow bind:nodes bind:edges {nodeTypes} fitView onnodeclick={selectNode}>
				<Background variant={BackgroundVariant.Dots} gap={16} />
				<Controls />
				<MiniMap pannable zoomable />
			</SvelteFlow>
			{#if store.nodes.length === 0}
				<div class="empty">
					No lineage yet. Trigger the producer:
					<code>uv run python scripts/medallion_demo.py --step 1</code> (then 2…5).
				</div>
			{/if}
		</section>

		<aside>
			<Tabs.Root value="events">
				<Tabs.List class="tablist">
					<Tabs.Trigger value="events" class="tab">Events</Tabs.Trigger>
					<Tabs.Trigger value="storage" class="tab">Storage (S3)</Tabs.Trigger>
					<Tabs.Trigger value="details" class="tab">Details</Tabs.Trigger>
				</Tabs.List>

				<Tabs.Content value="events" class="tabbody">
					{#if store.events.length === 0}
						<p class="hint">No events yet.</p>
					{/if}
					{#each store.events as ev (ev.seq)}
						<details class="event">
							<summary>
								<span class="badge" style:background={stateColor(ev.event_type)}>{ev.event_type}</span>
								<span class="mono job">{ev.job}</span>
								<span class="out mono">{ev.outputs.join(', ')}</span>
							</summary>
							<div class="who">{ev.author ?? '—'} · {ev.event_time}</div>
							<pre class="mono json">{JSON.stringify(ev.event, null, 2)}</pre>
						</details>
					{/each}
				</Tabs.Content>

				<Tabs.Content value="storage" class="tabbody">
					{#each store.datasets as ds (ds.name)}
						<div class="ds">
							<div class="ds-head">
								<span class="mono ds-name">{ds.name}</span>
								{#if ds.exists}
									<span class="hint">v{ds.current_version} · {ds.row_count} rows</span>
								{:else}
									<span class="hint">pending</span>
								{/if}
							</div>
							{#each ds.versions as v (v.version)}
								<div class="ver">
									<span class="chip ok">v{v.version}</span>
									<span class="fields mono">{v.fields.map((f) => f.name).join(', ')}</span>
								</div>
							{/each}
							{#if ds.lineage_jsonb}
								<details class="jsonb">
									<summary>embedded lineage JSONB</summary>
									<pre class="mono json">{JSON.stringify(ds.lineage_jsonb, null, 2)}</pre>
								</details>
							{/if}
						</div>
					{/each}
					{#if store.datasets.length === 0}
						<p class="hint">Storage peek is off (set LINEAGE_DEMO_DATA_ENABLED) or no data yet.</p>
					{/if}
				</Tabs.Content>

				<Tabs.Content value="details" class="tabbody">
					{#if !store.selected}
						<p class="hint">Click a dataset node to see the runs that produced it.</p>
					{:else}
						<h2 class="mono">{store.selected}</h2>
						<p class="hint">{selectedRuns.length} producing run(s)</p>
						{#each selectedRuns as r (r.run_id)}
							<div class="run" class:fail={/FAIL|ABORT/i.test(r.event_type ?? '')}>
								<div class="run-top">
									<span class="badge" style:background={stateColor(r.event_type)}>
										{r.dataset_version ? `v${r.dataset_version}` : r.event_type}
									</span>
									<span class="who">{r.author ?? '—'}</span>
								</div>
								<div class="who">{r.event_time}</div>
								{#if r.error_message}<div class="err">{r.error_message}</div>{/if}
							</div>
						{/each}
					{/if}
				</Tabs.Content>
			</Tabs.Root>
		</aside>
	</main>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100vh;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 16px;
		flex-wrap: wrap;
		padding: 12px 18px;
		border-bottom: 1px solid var(--line);
	}
	h1 {
		font-size: 16px;
		margin: 0;
		font-weight: 600;
	}
	.sub {
		color: var(--mut);
		font-size: 12px;
		font-weight: 400;
	}
	.legend {
		display: flex;
		gap: 12px;
		font-size: 11px;
		color: var(--mut);
	}
	.legend i {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		margin-right: 4px;
		vertical-align: middle;
	}
	.status {
		margin-left: auto;
		color: var(--mut);
		font-size: 12px;
	}
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--mut);
		margin-right: 4px;
	}
	.dot.on {
		background: var(--ok);
	}
	main {
		display: grid;
		grid-template-columns: 1fr 360px;
		flex: 1;
		min-height: 0;
	}
	.graph {
		position: relative;
		min-width: 0;
	}
	.empty {
		position: absolute;
		top: 16px;
		left: 16px;
		color: var(--mut);
		font-size: 13px;
	}
	.empty code {
		color: var(--ink);
	}
	aside {
		border-left: 1px solid var(--line);
		background: var(--panel);
		overflow: auto;
		display: flex;
		flex-direction: column;
	}
	:global(.tablist) {
		display: flex;
		border-bottom: 1px solid var(--line);
	}
	:global(.tab) {
		flex: 1;
		padding: 10px;
		background: transparent;
		border: none;
		color: var(--mut);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
	}
	:global(.tab[data-state='active']) {
		color: var(--ink);
		box-shadow: inset 0 -2px 0 var(--ok);
	}
	:global(.tabbody) {
		padding: 12px;
		overflow: auto;
	}
	.hint {
		color: var(--mut);
		font-size: 12px;
	}
	.badge {
		display: inline-block;
		padding: 1px 7px;
		border-radius: 7px;
		font-size: 11px;
		font-weight: 700;
		color: #06210f;
	}
	.event,
	.ds,
	.run {
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 8px 10px;
		margin-bottom: 8px;
		font-size: 12px;
	}
	.run.fail {
		border-color: var(--fail);
	}
	.event summary {
		display: flex;
		gap: 8px;
		align-items: center;
		cursor: pointer;
	}
	.job {
		color: var(--ink);
	}
	.out {
		color: var(--mut);
		margin-left: auto;
	}
	.who {
		color: var(--mut);
		font-size: 11px;
		margin-top: 4px;
	}
	.err {
		color: var(--fail);
		margin-top: 4px;
	}
	.json {
		font-size: 10.5px;
		background: #0c1018;
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 8px;
		margin: 6px 0 0;
		overflow: auto;
		max-height: 280px;
	}
	.ds-head {
		display: flex;
		justify-content: space-between;
		margin-bottom: 6px;
	}
	.ds-name {
		font-weight: 600;
	}
	.ver {
		display: flex;
		gap: 8px;
		align-items: baseline;
		margin: 3px 0;
	}
	.fields {
		font-size: 11px;
		color: var(--mut);
	}
	.chip.ok {
		background: var(--ok);
		color: #06210f;
		font-size: 10px;
		font-weight: 700;
		padding: 1px 7px;
		border-radius: 7px;
	}
	.run-top {
		display: flex;
		justify-content: space-between;
	}
	.jsonb summary {
		cursor: pointer;
		color: var(--mut);
		font-size: 11px;
		margin-top: 6px;
	}
	h2 {
		font-size: 13px;
		margin: 0 0 2px;
	}
</style>
