<script lang="ts" module>
	import MedallionNode, { type MedallionNodeType } from '$lib/MedallionNode.svelte';
	import JobNode, { type JobNodeType } from '$lib/JobNode.svelte';
	import ColumnNode, { type ColumnNodeType } from '$lib/ColumnNode.svelte';
	import type { NodeTypes } from '@xyflow/svelte';

	// svelte-flow rule 5: register node components ONCE at module scope, not inline.
	const nodeTypes: NodeTypes = { medallion: MedallionNode, job: JobNode, column: ColumnNode };
	type FlowNode = MedallionNodeType | JobNodeType | ColumnNodeType;
</script>

<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteFlow, Background, BackgroundVariant, Controls, MiniMap, Panel } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { Tabs } from 'bits-ui';
	import { Radio, Boxes, Cpu, Columns3 } from '@lucide/svelte';
	import FlowAutoFit from '$lib/FlowAutoFit.svelte';
	import { LineageState } from '$lib/store.svelte';
	import { SearchBar, StatusBoard, enter, stagger, countUp } from '@lance/ui';
	import { fetchSearch } from '$lib/api';
	import { LAYER, type DemoDataset } from '$lib/types';

	const store = new LineageState();

	// Which graph plane is shown — Datasets / Jobs (like Marquez) + Columns (field-to-field, #24).
	let graphView = $state<'datasets' | 'jobs' | 'columns'>('datasets');
	// Browse (GOAL 4 A3): filter the governed /datasets catalog by name / namespace / tag, then click a
	// row to focus that dataset — the browsable entry point that replaces the hardcoded name list.
	let browseQuery = $state('');
	let nsFilter = $state(''); // '' = all namespaces (fed by the governed /namespaces list)

	// Derived primitives so the count-up labels only re-animate when the number actually changes.
	const datasetCount = $derived(store.nodes.length);
	const eventCount = $derived(store.events.length);
	const browseResults = $derived.by(() => {
		const scoped = nsFilter ? store.catalog.filter((d) => d.namespace === nsFilter) : store.catalog;
		const q = browseQuery.trim().toLowerCase();
		if (!q) return scoped;
		return scoped.filter(
			(d) =>
				d.name.toLowerCase().includes(q) ||
				(d.namespace ?? '').toLowerCase().includes(q) ||
				(d.tags ?? []).some((t) => t.toLowerCase().includes(q))
		);
	});

	let nodes = $state.raw<FlowNode[]>([]);
	let edges = $state.raw<
		{ id: string; source: string; target: string; animated: boolean; type: string; label?: string; class?: string }[]
	>([]);
	// Re-fit the viewport only when the node-set or the view changes (not on every data poll).
	const fitKey = $derived(graphView + '|' + nodes.map((n) => n.id).join(','));

	// Current run-state per dataset: the latest run (by updated_at) that lists it as an output.
	const runStateByDataset = $derived.by(() => {
		const m: Record<string, string> = {};
		const ordered = [...store.runs].sort((a, b) => (a.updated_at ?? '').localeCompare(b.updated_at ?? ''));
		for (const r of ordered) {
			if (!r.state) continue;
			for (const out of r.outputs ?? []) m[out] = r.state;
		}
		return m;
	});

	$effect(() => {
		store.poll();
		const timer = setInterval(() => store.poll(), 2000);
		return () => clearInterval(timer);
	});

	// In Columns view, keep the selected dataset's field-to-field graph fresh on its own poll.
	$effect(() => {
		if (graphView !== 'columns' || !store.selected) return;
		const name = store.selected;
		store.loadColumns(name);
		const t = setInterval(() => store.loadColumns(name), 2000);
		return () => clearInterval(t);
	});

	// Rebuild the active graph plane whenever the polled data (or the chosen view) changes.
	// Reconcile, don't rebuild: keep each node's identity + dragged position across the 2s poll.
	$effect(() => {
		// Read the current nodes UNTRACKED — we only want their last positions to carry forward; tracking
		// `nodes` here (the var we reassign below) would make this effect retrigger itself → infinite loop.
		const prev = new Map(untrack(() => nodes).map((node) => [node.id, node]));

		if (graphView === 'columns') {
			// Columns plane (#24): the selected dataset's field-to-field lineage. Columns are laid out by
			// their owning dataset's medallion layer (x) and stacked (y); edges carry the transformation kind.
			const cg = store.columnGraph;
			const root = store.selected;
			if (!cg || !root) {
				nodes = [];
				edges = [];
				return;
			}
			const masked = new Set(
				(cg.edges ?? []).filter((e) => e.masking).map((e) => `${e.target_dataset}::${e.target_field}`)
			);
			const perLayer: Record<number, number> = {};
			nodes = (cg.columns ?? []).map((c) => {
				const layer = LAYER[c.dataset] ?? 4;
				const row = (perLayer[layer] = (perLayer[layer] ?? 0) + 1) - 1;
				const id = `${c.dataset}::${c.field}`;
				return {
					id,
					type: 'column' as const,
					position: prev.get(id)?.position ?? { x: 20 + layer * 230, y: 24 + row * 76 },
					data: { dataset: c.dataset, field: c.field, type: c.type, layer, masked: masked.has(id), isRoot: c.dataset === root }
				};
			});
			edges = (cg.edges ?? []).map((e) => {
				const s = `${e.source_dataset}::${e.source_field}`;
				const t = `${e.target_dataset}::${e.target_field}`;
				return {
					id: `${s}->${t}`,
					source: s,
					target: t,
					animated: true,
					type: 'smoothstep',
					label: e.transformation_subtype || e.transformation_type || '',
					class: e.masking ? 'masked-edge' : ''
				};
			});
			return;
		}

		if (graphView === 'jobs') {
			// Jobs plane (like Marquez's job lineage): one node per job; an edge producing-job → consuming
			// job whenever a job's input dataset was written by another job.
			const jobs = new Map<
				string,
				{ author?: string | null; state?: string | null; inputs: Set<string>; outputs: Set<string>; failed: boolean }
			>();
			const producedBy = new Map<string, Set<string>>();
			for (const ev of [...store.events].reverse()) {
				if (!ev.job) continue;
				const j = jobs.get(ev.job) ?? { author: ev.author, state: ev.event_type, inputs: new Set(), outputs: new Set(), failed: false };
				j.author = ev.author ?? j.author;
				j.state = ev.event_type ?? j.state;
				if (/FAIL|ABORT/i.test(ev.event_type ?? '')) j.failed = true;
				for (const o of ev.outputs ?? []) {
					j.outputs.add(o);
					if (!producedBy.has(o)) producedBy.set(o, new Set());
					producedBy.get(o)!.add(ev.job);
				}
				for (const i of ev.inputs ?? []) j.inputs.add(i);
				jobs.set(ev.job, j);
			}
			const perCol: Record<number, number> = {};
			nodes = [...jobs.entries()].map(([job, j]) => {
				const layer = Math.max(0, ...[...j.outputs].map((o) => LAYER[o] ?? 4));
				const row = (perCol[layer] = (perCol[layer] ?? 0) + 1) - 1;
				return {
					id: job,
					type: 'job' as const,
					position: prev.get(job)?.position ?? { x: 30 + layer * 280, y: 40 + row * 130 },
					data: { id: job.replace(/^ray-jobs\//, ''), author: j.author, state: j.state, outputs: [...j.outputs], failed: j.failed, selected: store.selected === job }
				};
			});
			const seen = new Set<string>();
			const je: typeof edges = [];
			for (const [job, j] of jobs) {
				for (const inp of j.inputs) {
					for (const pj of producedBy.get(inp) ?? []) {
						if (pj === job || seen.has(`${pj}|${job}`)) continue;
						seen.add(`${pj}|${job}`);
						je.push({ id: `${pj}->${job}`, source: pj, target: job, animated: true, type: 'smoothstep' });
					}
				}
			}
			edges = je;
			return;
		}

		// Datasets plane (default).
		nodes = store.nodes.map((n) => {
			const runs = store.producers[n.id] ?? [];
			const versions = [...new Set(runs.map((r) => r.dataset_version).filter(Boolean) as string[])].sort();
			const failed = runs.some((r) => /FAIL|ABORT/i.test(r.event_type ?? ''));
			const layer = LAYER[n.id] ?? 4;
			return {
				id: n.id,
				type: 'medallion' as const,
				position: prev.get(n.id)?.position ?? { x: 30 + layer * 300, y: 150 },
				data: {
					id: n.id,
					layer,
					source_uri: n.source_uri,
					tags: n.tags ?? [],
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
		// Column nodes aren't datasets; in Columns view keep the dataset selection intact.
		if (graphView === 'columns') return;
		const ev = e as { node?: { id: string }; targetNode?: { id: string } };
		store.selected = ev.node?.id ?? ev.targetNode?.id ?? null;
	}

	const stateColor = (s?: string | null) =>
		/FAIL|ABORT/i.test(s ?? '') ? 'var(--fail)' : s === 'COMPLETE' ? 'var(--ok)' : 'var(--mut)';

	const selectedRuns = $derived(store.selected ? (store.producers[store.selected] ?? []) : []);

	// Upstream / downstream for the selected dataset, from the DERIVED_FROM edges (source derived from
	// target): upstream = what it was derived from; downstream = what derives from it.
	const upstream = $derived(
		store.selected ? store.edges.filter((e) => e.source === store.selected).map((e) => e.target) : []
	);
	const downstream = $derived(
		store.selected ? store.edges.filter((e) => e.target === store.selected).map((e) => e.source) : []
	);

	// Per-version column evolution, marking columns added since the previous Lance version.
	function evolution(ds: DemoDataset) {
		const out: { version: number; cols: { name: string; type: string; added: boolean }[] }[] = [];
		let prev = new Set<string>();
		for (const v of ds.versions ?? []) {
			const fields = v.fields ?? [];
			out.push({
				version: v.version,
				cols: fields.map((f) => ({ name: f.name, type: f.type, added: !prev.has(f.name) }))
			});
			prev = new Set(fields.map((f) => f.name));
		}
		return out;
	}
	const currentCols = (ds: DemoDataset) => (ds.versions ?? []).at(-1)?.fields ?? [];
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
			<Radio size={13} class={store.online ? 'live-ic on' : 'live-ic'} />
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
				<FlowAutoFit trigger={fitKey} />
				<Panel position="top-left">
					<div class="viewtoggle" role="tablist" aria-label="Graph view">
						<button class="vt" class:on={graphView === 'datasets'} role="tab" aria-selected={graphView === 'datasets'} onclick={() => (graphView = 'datasets')}>
							<Boxes size={13} /> Datasets
						</button>
						<button class="vt" class:on={graphView === 'jobs'} role="tab" aria-selected={graphView === 'jobs'} onclick={() => (graphView = 'jobs')}>
							<Cpu size={13} /> Jobs
						</button>
						<button class="vt" class:on={graphView === 'columns'} role="tab" aria-selected={graphView === 'columns'} onclick={() => (graphView = 'columns')}>
							<Columns3 size={13} /> Columns
						</button>
					</div>
				</Panel>
			</SvelteFlow>
			{#if graphView === 'columns' && !store.selected}
				<div class="empty">
					<b>Pick a dataset first.</b><br />
					Select a node in <b>Datasets</b>, then switch back to <b>Columns</b> to see its
					field-to-field lineage.
				</div>
			{:else if graphView === 'columns' && (store.columnGraph?.columns?.length ?? 0) === 0}
				<div class="empty">
					<b>No column lineage for {store.selected} yet.</b><br />
					Producers must emit the <code>columnLineage</code> facet (the medallion does).
				</div>
			{:else if graphView !== 'columns' && store.nodes.length === 0}
				<div class="empty">
					<b>Nothing yet — you trigger it.</b><br />
					<code>uv run scripts/medallion_demo.py --step 1</code> → bronze appears.<br />
					Then <code>--step 2</code> (a failed run), <code>3</code> (silver v1), <code>4</code>
					(silver v2), <code>5</code> (gold).
				</div>
			{/if}
		</section>

		<aside {@attach enter({ delay: 0.12 })}>
			<Tabs.Root value="browse">
				<Tabs.List class="tablist">
					<Tabs.Trigger value="browse" class="tab">Browse ({store.catalog.length})</Tabs.Trigger>
					<Tabs.Trigger value="status" class="tab">Status ({store.runs.length})</Tabs.Trigger>
					<Tabs.Trigger value="jobs" class="tab">Jobs ({store.jobs.length})</Tabs.Trigger>
					<Tabs.Trigger value="events" class="tab">Events ({store.events.length})</Tabs.Trigger>
					<Tabs.Trigger value="details" class="tab">Details</Tabs.Trigger>
				</Tabs.List>

				<Tabs.Content value="browse" class="tabbody">
					<p class="hint board-intro">
						Every dataset the lineage graph knows — search by <b>name</b>, <b>namespace</b>, or
						<b>tag</b>, then click one to focus it. No need to know a name in advance.
					</p>
					<!-- Server-side GOVERNED search (P1 Search tier 1): reaches tags + the column
					     inventory the client-side list below can't see; hits show WHY they matched. -->
					<SearchBar
						search={async (q) => (await fetchSearch(q))?.results ?? []}
						onselect={(name) => (store.selected = name)}
					/>
					{#if store.namespaceList.length}
						<select class="browse-ns-filter mono" bind:value={nsFilter} aria-label="Namespace">
							<option value="">all namespaces</option>
							{#each store.namespaceList as ns (ns)}
								<option value={ns}>{ns}</option>
							{/each}
						</select>
					{/if}
					<input
						class="browse-input mono"
						type="search"
						placeholder="filter datasets…"
						bind:value={browseQuery}
						aria-label="Filter datasets"
					/>
					<ul class="browse-list">
						{#each browseResults as d (d.name)}
							<li>
								<button
									class="browse-row"
									class:on={store.selected === d.name}
									onclick={() => (store.selected = d.name)}
								>
									<span class="browse-name mono">{d.name}</span>
									{#if d.namespace}<span class="browse-ns">{d.namespace}</span>{/if}
									{#each d.tags ?? [] as t (t)}<span class="browse-tag">{t}</span>{/each}
								</button>
							</li>
						{:else}
							<p class="hint">No datasets match “{browseQuery}”.</p>
						{/each}
					</ul>
				</Tabs.Content>

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
								<span class="out mono">{(ev.outputs ?? []).join(', ')}</span>
							</summary>
							<div class="who">{ev.author ?? '—'} · {ev.event_time}</div>
							<pre class="mono json">{JSON.stringify(ev.event, null, 2)}</pre>
						</details>
					{/each}
				</Tabs.Content>

				<Tabs.Content value="jobs" class="tabbody">
					<p class="hint board-intro">
						Every compute identity that has run — governed like the rest: a job is listed only
						if you may see every dataset it wrote.
					</p>
					<ul class="browse-list job-list">
						{#each store.jobs as j (j.namespace + '/' + j.name)}
							<li>
								<div class="job-row">
									<span class="job-name mono">{j.name}</span>
									<span class="browse-ns">{j.namespace}</span>
									{#each j.outputs ?? [] as out (out)}
										<button class="browse-tag mono" onclick={() => (store.selected = out)}>{out}</button>
									{/each}
								</div>
							</li>
						{:else}
							<p class="hint">No jobs recorded yet.</p>
						{/each}
					</ul>
				</Tabs.Content>

				<Tabs.Content value="details" class="tabbody">
					{#if !store.selected}
						<p class="hint">Click a dataset node in the graph to see the runs that produced it.</p>
					{:else}
						<h2 class="mono">{store.selected}</h2>
						{#if upstream.length || downstream.length}
							<div class="rel">
								{#if upstream.length}
									<div class="rel-group">
										<span class="rel-label">Upstream</span>
										{#each upstream as u (u)}
											<button class="rel-chip mono" onclick={() => (store.selected = u)}>{u}</button>
										{/each}
									</div>
								{/if}
								{#if downstream.length}
									<div class="rel-group">
										<span class="rel-label">Downstream</span>
										{#each downstream as d (d)}
											<button class="rel-chip mono" onclick={() => (store.selected = d)}>{d}</button>
										{/each}
									</div>
								{/if}
								<button class="rel-cols" onclick={() => (graphView = 'columns')}>
									<Columns3 size={12} /> View column lineage
								</button>
							</div>
						{/if}
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
	:global(.live-ic) {
		color: var(--mut);
		transition: color 0.3s var(--ease);
	}
	:global(.live-ic.on) {
		color: var(--ok);
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
	/* A masking column derivation (e.g. a PII hash) reads as a red dashed edge. */
	:global(.masked-edge .svelte-flow__edge-path) {
		stroke: var(--fail);
		stroke-dasharray: 5 3;
	}
	.empty {
		position: absolute;
		top: 18px;
		left: 18px;
		color: var(--mut);
		font-size: 13px;
		line-height: 1.7;
	}
	.viewtoggle {
		display: flex;
		gap: 2px;
		padding: 3px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 999px;
		box-shadow: var(--shadow);
	}
	.vt {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 11px;
		border: none;
		background: transparent;
		color: var(--mut);
		font-size: 12px;
		font-weight: 600;
		border-radius: 999px;
		cursor: pointer;
		transition:
			color 0.2s var(--ease),
			background 0.2s var(--ease);
	}
	.vt:hover {
		color: var(--ink);
	}
	.vt.on {
		color: var(--ink);
		background: color-mix(in srgb, var(--accent) 18%, transparent);
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

	/* ---- selected-dataset relationships (upstream / downstream / column-lineage) ---- */
	.rel {
		margin: 6px 0 12px;
		padding-bottom: 10px;
		border-bottom: 1px solid var(--line);
	}
	.rel-group {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 5px;
		margin-bottom: 6px;
	}
	.rel-label {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.4px;
		color: var(--mut);
		margin-right: 2px;
	}
	.rel-chip {
		font-size: 11px;
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--panel);
		color: var(--ink);
		cursor: pointer;
		transition:
			border-color 0.2s var(--ease),
			background 0.2s var(--ease);
	}
	.rel-chip:hover {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
	}
	.rel-cols {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		margin-top: 2px;
		padding: 3px 9px;
		border: none;
		border-radius: 6px;
		background: color-mix(in srgb, var(--accent) 16%, transparent);
		color: var(--ink);
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.rel-cols:hover {
		background: color-mix(in srgb, var(--accent) 26%, transparent);
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
	/* Browse panel (GOAL 4 A3) — the governed /datasets list + filter */
	.job-name {
		font-size: 0.85rem;
	}
	.job-row {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		flex-wrap: wrap;
		padding: 0.4rem 0.55rem;
	}
	.browse-ns-filter {
		width: 100%;
		margin: 0.35rem 0;
		padding: 0.35rem 0.55rem;
		border-radius: 0.5rem;
		border: 1px solid color-mix(in oklab, currentColor 25%, transparent);
		background: transparent;
		color: inherit;
		font-size: 0.8rem;
	}
	.browse-input {
		width: 100%;
		box-sizing: border-box;
		margin: 6px 0 8px;
		padding: 6px 10px;
		font-size: 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: var(--panel);
		color: var(--ink);
	}
	.browse-input:focus {
		outline: none;
		border-color: var(--accent);
	}
	.browse-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.browse-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: var(--panel);
		color: var(--ink);
		cursor: pointer;
		text-align: left;
		transition:
			border-color 0.2s var(--ease),
			background 0.2s var(--ease);
	}
	.browse-row:hover {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.browse-row.on {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 20%, transparent);
	}
	.browse-name {
		font-size: 12px;
		font-weight: 600;
	}
	.browse-ns {
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--accent) 16%, transparent);
		color: var(--ink);
	}
	.browse-tag {
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 999px;
		border: 1px solid var(--line);
		color: var(--mut);
	}
</style>
