<script lang="ts">
	import { SvelteFlow, Background, BackgroundVariant, Controls, MiniMap } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { Tabs } from 'bits-ui';
	import MedallionNode, { type MedallionNodeType } from '$lib/MedallionNode.svelte';
	import StatusBoard from '$lib/StatusBoard.svelte';
	import { enter, stagger, countUp } from '$lib/attachments';
	import { LineageState } from '$lib/store.svelte';
	import { LAYER, type DemoDataset } from '$lib/types';

	const store = new LineageState();
	const nodeTypes = { medallion: MedallionNode };

	// Derived primitives so the count-up labels only re-animate when the number actually changes.
	const datasetCount = $derived(store.nodes.length);
	const eventCount = $derived(store.events.length);

	let nodes = $state.raw<MedallionNodeType[]>([]);
	let edges = $state.raw<{ id: string; source: string; target: string; animated: boolean; type: string }[]>([]);

	// Current run-state per dataset: the latest run (by updated_at) that lists it as an output.
	const runStateByDataset = $derived.by(() => {
		const m: Record<string, string> = {};
		const ordered = [...store.runs].sort((a, b) => (a.updated_at ?? '').localeCompare(b.updated_at ?? ''));
		for (const r of ordered) {
			if (!r.state) continue;
			for (const out of r.outputs) m[out] = r.state;
		}
		return m;
	});

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
					selected: store.selected === n.id,
					runState: runStateByDataset[n.id] ?? null
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

	// Per-version column evolution, marking columns added since the previous Lance version.
	function evolution(ds: DemoDataset) {
		const out: { version: number; cols: { name: string; type: string; added: boolean }[] }[] = [];
		let prev = new Set<string>();
		for (const v of ds.versions) {
			out.push({
				version: v.version,
				cols: v.fields.map((f) => ({ name: f.name, type: f.type, added: !prev.has(f.name) }))
			});
			prev = new Set(v.fields.map((f) => f.name));
		}
		return out;
	}
	const currentCols = (ds: DemoDataset) => ds.versions.at(-1)?.fields ?? [];
</script>

<div class="app">
	<header {@attach stagger({ each: 0.08 })}>
		<h1>Lance Lineage <span class="sub">live medallion demo</span></h1>
		<p class="explain">
			You're the producer — trigger steps with
			<code>medallion_demo.py --step 1</code> (then 2…5). Each step writes a real Lance table on RustFS
			and emits one OpenLineage event. Watch the <b>graph</b> (who derived what), the <b>events</b>
			(raw OpenLineage), and the <b>Lance tables</b> below evolve.
		</p>
		<div class="status">
			<span class="dot" class:on={store.online}></span>
			<span class="state-word" class:live={store.online}>{store.online ? 'live' : 'waiting'}</span>
			<span class="sep">·</span>
			<span class="num mono" {@attach countUp(datasetCount)}>0</span> datasets
			<span class="sep">·</span>
			<span class="num mono" {@attach countUp(eventCount)}>0</span> events
			{#if store.lastUpdated}<span class="sep">·</span> <span class="ts">{store.lastUpdated}</span>{/if}
		</div>
	</header>

	<div class="top">
		<section class="graph" {@attach enter({ delay: 0.05 })}>
			<SvelteFlow bind:nodes bind:edges {nodeTypes} fitView onnodeclick={selectNode}>
				<Background variant={BackgroundVariant.Dots} gap={16} />
				<Controls />
				<MiniMap pannable zoomable />
			</SvelteFlow>
			{#if store.nodes.length === 0}
				<div class="empty">
					<b>Nothing yet — you trigger it.</b><br />
					<code>uv run scripts/medallion_demo.py --step 1</code> → bronze appears.<br />
					Then <code>--step 2</code> (a failed run), <code>3</code> (silver v1), <code>4</code>
					(silver v2), <code>5</code> (gold).
				</div>
			{/if}
		</section>

		<aside {@attach enter({ delay: 0.12 })}>
			<Tabs.Root value="status">
				<Tabs.List class="tablist">
					<Tabs.Trigger value="status" class="tab">Status ({store.runs.length})</Tabs.Trigger>
					<Tabs.Trigger value="events" class="tab">Events ({store.events.length})</Tabs.Trigger>
					<Tabs.Trigger value="details" class="tab">Details</Tabs.Trigger>
				</Tabs.List>

				<Tabs.Content value="status" class="tabbody">
					<p class="hint board-intro">
						Live run lifecycle — each step emits <b>START → RUNNING (progress) → COMPLETE/FAIL</b>.
						The board folds those events to each run's current state (last-wins).
					</p>
					<StatusBoard runs={store.runs} />
				</Tabs.Content>

				<Tabs.Content value="events" class="tabbody">
					{#if store.events.length === 0}
						<p class="hint">No OpenLineage events yet. Trigger a step.</p>
					{/if}
					{#each store.events as ev (ev.seq)}
						<details class="event" {@attach enter({ y: 6 })}>
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

				<Tabs.Content value="details" class="tabbody">
					{#if !store.selected}
						<p class="hint">Click a dataset node in the graph to see the runs that produced it.</p>
					{:else}
						<h2 class="mono">{store.selected}</h2>
						<p class="hint">{selectedRuns.length} producing run(s)</p>
						{#each selectedRuns as r (r.run_id)}
							<div class="run" class:fail={/FAIL|ABORT/i.test(r.event_type ?? '')} {@attach enter({ y: 6 })}>
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
	</div>

	<section class="storage" {@attach enter({ delay: 0.18 })}>
		<div class="storage-head">
			Lance tables on RustFS <span class="hint">— real object storage; columns appear as you run steps</span>
		</div>
		<div class="cards">
			{#each store.datasets as ds (ds.name)}
				<div class="card" class:pending={!ds.exists} {@attach enter({ y: 10 })}>
					<div class="card-head">
						<span class="mono ds-name">{ds.name}</span>
						{#if ds.exists}
							<span class="hint">v{ds.current_version} · {ds.row_count} rows</span>
						{:else}
							<span class="hint pending-tag">not created yet</span>
						{/if}
					</div>
					<div class="uri mono">{ds.uri}</div>
					{#if ds.exists}
						<table class="schema">
							<thead><tr><th>column</th><th>type</th></tr></thead>
							<tbody>
								{#each currentCols(ds) as f (f.name)}
									<tr><td class="mono">{f.name}</td><td class="mono ty">{f.type}</td></tr>
								{/each}
							</tbody>
						</table>
						<div class="evo">
							<div class="evo-label">version history</div>
							{#each evolution(ds) as v (v.version)}
								<div class="evo-row">
									<span class="chip ok">v{v.version}</span>
									<span class="evo-cols">
										{#each v.cols as c (c.name)}
											<span class="col mono" class:added={c.added}>{c.name}</span>
										{/each}
									</span>
								</div>
							{/each}
						</div>
						{#if ds.lineage_jsonb}
							<details class="jsonb">
								<summary>embedded lineage JSONB</summary>
								<pre class="mono json">{JSON.stringify(ds.lineage_jsonb, null, 2)}</pre>
							</details>
						{/if}
					{:else}
						<div class="hint pend">waiting for a step to write this table…</div>
					{/if}
				</div>
			{/each}
			{#if store.datasets.length === 0}
				<p class="hint">Storage peek is off (LINEAGE_DEMO_DATA_ENABLED).</p>
			{/if}
		</div>
	</section>
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
		padding: 11px 18px;
		border-bottom: 1px solid var(--line);
		background: linear-gradient(180deg, var(--panel-2), transparent);
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
	.explain {
		margin: 0;
		font-size: 12px;
		color: var(--mut);
		max-width: 720px;
	}
	.explain code,
	.empty code {
		color: var(--ink);
		background: #0c1018;
		padding: 0 4px;
		border-radius: 4px;
	}
	.explain b {
		color: var(--ink);
	}
	.status {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-left: auto;
		color: var(--mut);
		font-size: 12px;
		white-space: nowrap;
	}
	.sep {
		color: var(--line-2);
	}
	.num {
		color: var(--ink);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.state-word {
		text-transform: uppercase;
		letter-spacing: 0.4px;
		font-size: 11px;
		font-weight: 700;
		color: var(--mut);
	}
	.state-word.live {
		color: var(--ok);
	}
	.ts {
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--mut);
		transition: background 0.3s var(--ease);
	}
	.dot.on {
		background: var(--ok);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 22%, transparent);
	}
	.top {
		display: grid;
		grid-template-columns: 1fr 340px;
		flex: 1 1 0;
		min-height: 0;
	}
	.graph {
		position: relative;
		min-width: 0;
	}
	.empty {
		position: absolute;
		top: 18px;
		left: 18px;
		color: var(--mut);
		font-size: 13px;
		line-height: 1.7;
	}
	aside {
		border-left: 1px solid var(--line);
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}
	:global(.tablist) {
		display: flex;
		border-bottom: 1px solid var(--line);
	}
	:global(.tab) {
		flex: 1;
		padding: 10px 9px;
		background: transparent;
		border: none;
		color: var(--mut);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition:
			color 0.2s var(--ease),
			box-shadow 0.2s var(--ease);
	}
	:global(.tab:hover) {
		color: var(--ink);
	}
	:global(.tab[data-state='active']) {
		color: var(--ink);
		box-shadow: inset 0 -2px 0 var(--accent);
	}
	:global(.tabbody) {
		padding: 12px;
		overflow: auto;
	}
	.hint {
		color: var(--mut);
		font-size: 12px;
	}
	.board-intro {
		margin: 0 0 10px;
		line-height: 1.5;
	}
	.board-intro b {
		color: var(--ink);
	}
	.badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 700;
		color: #06210f;
	}
	.event,
	.run {
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		padding: 8px 10px;
		margin-bottom: 8px;
		font-size: 12px;
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		transition: border-color 0.2s var(--ease);
	}
	.event:hover,
	.run:hover {
		border-color: var(--line-2);
	}
	.run.fail {
		border-color: color-mix(in srgb, var(--fail) 55%, var(--line));
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
		max-height: 220px;
	}
	.run-top {
		display: flex;
		justify-content: space-between;
	}

	/* ---- Storage (Lance tables on RustFS) ---- */
	.storage {
		flex: 0 0 auto;
		max-height: 40vh;
		overflow: auto;
		border-top: 1px solid var(--line);
		padding: 12px 14px 16px;
		background: var(--bg-2);
	}
	.storage-head {
		font-size: 13px;
		font-weight: 600;
		margin-bottom: 10px;
	}
	.cards {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 12px;
	}
	.card {
		border: 1px solid var(--line);
		border-radius: var(--radius);
		padding: 11px 13px;
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		box-shadow: var(--shadow);
		transition:
			border-color 0.2s var(--ease),
			transform 0.2s var(--ease);
	}
	.card:hover {
		border-color: var(--line-2);
		transform: translateY(-2px);
	}
	.card.pending {
		opacity: 0.55;
		border-style: dashed;
		box-shadow: none;
	}
	.card-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.ds-name {
		font-weight: 600;
		font-size: 13px;
	}
	.pending-tag {
		font-style: italic;
	}
	.uri {
		font-size: 11px;
		color: #6f86a6;
		margin: 2px 0 8px;
		word-break: break-all;
	}
	table.schema {
		width: 100%;
		border-collapse: collapse;
		font-size: 11.5px;
		margin-bottom: 8px;
	}
	table.schema th {
		text-align: left;
		color: var(--mut);
		font-weight: 600;
		border-bottom: 1px solid var(--line);
		padding: 2px 4px;
		text-transform: uppercase;
		font-size: 10px;
	}
	table.schema td {
		padding: 2px 4px;
		border-bottom: 1px solid #1b2532;
	}
	.ty {
		color: var(--mut);
	}
	.evo-label {
		font-size: 10px;
		text-transform: uppercase;
		color: var(--mut);
		margin: 2px 0 4px;
	}
	.evo-row {
		display: flex;
		gap: 8px;
		align-items: baseline;
		margin: 3px 0;
	}
	.evo-cols {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.col {
		font-size: 10.5px;
		color: var(--mut);
		padding: 0 5px;
		border-radius: 5px;
		background: #1b2532;
	}
	.col.added {
		color: #06210f;
		background: var(--ok);
		font-weight: 700;
	}
	.chip.ok {
		background: var(--ok);
		color: #06210f;
		font-size: 10px;
		font-weight: 700;
		padding: 1px 7px;
		border-radius: 7px;
	}
	.jsonb summary {
		cursor: pointer;
		color: var(--mut);
		font-size: 11px;
		margin-top: 8px;
	}
	.pend {
		margin-top: 8px;
		font-style: italic;
	}
	h2 {
		font-size: 13px;
		margin: 0 0 2px;
	}
</style>
