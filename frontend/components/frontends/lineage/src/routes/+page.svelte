<script lang="ts" module>
	import MedallionNode, { type MedallionNodeType } from '$lib/MedallionNode.svelte';
	import JobNode, { type JobNodeType } from '$lib/JobNode.svelte';
	import type { NodeTypes } from '@xyflow/svelte';

	// svelte-flow rule 5: register node components ONCE at module scope, not inline.
	const nodeTypes: NodeTypes = { medallion: MedallionNode, job: JobNode };
	type FlowNode = MedallionNodeType | JobNodeType;
</script>

<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import {
		SvelteFlow,
		Background,
		BackgroundVariant,
		Controls,
		MiniMap,
		Panel,
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { Radio, Boxes, Cpu } from '@lucide/svelte';
	import FlowAutoFit from '$lib/FlowAutoFit.svelte';
	import { LineageState } from '$lib/store.svelte';
	import { countUp, stagger } from '@rask/ui/motion';
	import { LAYER, type GraphEdge } from '$lib/types';

	const POLL_MS = 5000;

	const store = new LineageState();

	// Which graph plane is shown — Datasets / Jobs (like Marquez). Columns is a first-class view
	// of its own (`/lineage/columns`); the sidebar's list views carry the rest of the old aside.
	let graphView = $state<'datasets' | 'jobs'>('datasets');

	const datasetCount = $derived(store.nodes.length);
	// Honest status line (the old header could claim WAITING while the canvas showed datasets):
	// connecting → first poll still in flight; live → last poll succeeded; offline → last poll
	// failed, the canvas KEEPS the last good state and says so.
	const status = $derived(!store.settled ? 'connecting' : store.online ? 'live' : 'offline');

	$effect(() => {
		store.poll();
		const timer = setInterval(() => store.poll(), POLL_MS);
		return () => clearInterval(timer);
	});

	let nodes = $state.raw<FlowNode[]>([]);
	let edges = $state.raw<
		{ id: string; source: string; target: string; animated: boolean; type: string }[]
	>([]);
	/** Last layout-build cost (ms) — measured around the node/edge rebuild, shown in the corner. */
	let buildMs = $state(0);
	// Re-fit the viewport only when the node-set or the view changes (not on every data poll).
	const fitKey = $derived(graphView + '|' + nodes.map((n) => n.id).join(','));

	// Current run-state per dataset: the latest run (by updated_at) that lists it as an output.
	const runStateByDataset = $derived.by(() => {
		const m: Record<string, string> = {};
		const ordered = [...store.runs].sort((a, b) =>
			(a.updated_at ?? '').localeCompare(b.updated_at ?? ''),
		);
		for (const r of ordered) {
			if (!r.state) continue;
			for (const out of r.outputs ?? []) m[out] = r.state;
		}
		return m;
	});

	/** Derivation depth per dataset from the DERIVED_FROM edges (`source` derived from `target` ⇒
	 * `target` is upstream). Longest-path with an iteration cap (a cyclic payload can't loop
	 * forever). Replaces the hardcoded medallion name map, which piled every foreign dataset onto
	 * one x column where their labels overlapped. */
	function depths(ids: string[], graphEdges: GraphEdge[]): Map<string, number> {
		const depth = new Map<string, number>();
		for (const id of ids) depth.set(id, 0);
		for (let i = 0; i < depth.size; i += 1) {
			let changed = false;
			for (const e of graphEdges) {
				// e.source derived_from e.target: source sits one column right of target.
				const next = (depth.get(e.target) ?? 0) + 1;
				if (e.source !== e.target && next > (depth.get(e.source) ?? 0)) {
					depth.set(e.source, next);
					changed = true;
				}
			}
			if (!changed) break;
		}
		return depth;
	}

	// Rebuild the active graph plane whenever the polled data (or the chosen view) changes.
	// Reconcile, don't rebuild: keep each node's identity + dragged position across the poll.
	$effect(() => {
		// Read the current nodes UNTRACKED — only their last positions carry forward; tracking
		// `nodes` (the var we reassign below) would make this effect retrigger itself.
		const prev = new Map(untrack(() => nodes).map((node) => [node.id, node]));
		const t0 = performance.now();

		if (graphView === 'jobs') {
			// Jobs plane (like Marquez's job lineage): one node per job; an edge producing-job →
			// consuming job whenever a job's input dataset was written by another job.
			const jobs = new Map<
				string,
				{
					author?: string | null;
					state?: string | null;
					inputs: Set<string>;
					outputs: Set<string>;
					failed: boolean;
				}
			>();
			const producedBy = new Map<string, Set<string>>();
			for (const ev of [...store.events].reverse()) {
				if (!ev.job) continue;
				const j = jobs.get(ev.job) ?? {
					author: ev.author,
					state: ev.event_type,
					inputs: new Set(),
					outputs: new Set(),
					failed: false,
				};
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
			const dsDepth = depths(
				store.nodes.map((n) => n.id),
				store.edges,
			);
			const perCol: Record<number, number> = {};
			nodes = [...jobs.entries()].map(([job, j]) => {
				const layer = Math.max(0, ...[...j.outputs].map((o) => dsDepth.get(o) ?? 0));
				const row = (perCol[layer] = (perCol[layer] ?? 0) + 1) - 1;
				return {
					id: job,
					type: 'job' as const,
					position: prev.get(job)?.position ?? { x: 30 + layer * 280, y: 40 + row * 130 },
					data: {
						id: job.replace(/^ray-jobs\//, ''),
						author: j.author,
						state: j.state,
						outputs: [...j.outputs],
						failed: j.failed,
						selected: false,
					},
				};
			});
			const seen = new Set<string>();
			const je: typeof edges = [];
			for (const [job, j] of jobs) {
				for (const inp of j.inputs) {
					for (const pj of producedBy.get(inp) ?? []) {
						if (pj === job || seen.has(`${pj}|${job}`)) continue;
						seen.add(`${pj}|${job}`);
						je.push({
							id: `${pj}->${job}`,
							source: pj,
							target: job,
							animated: true,
							type: 'smoothstep',
						});
					}
				}
			}
			edges = je;
			buildMs = Math.round((performance.now() - t0) * 10) / 10;
			return;
		}

		// Datasets plane (default): x = derivation depth (computed, so unrelated datasets never
		// stack on one overlapping column), y = per-depth row stagger.
		const dsDepth = depths(
			store.nodes.map((n) => n.id),
			store.edges,
		);
		const perLayer: Record<number, number> = {};
		nodes = store.nodes.map((n) => {
			const runs = store.producers[n.id] ?? [];
			const versions = [
				...new Set(runs.map((r) => r.dataset_version).filter(Boolean) as string[]),
			].sort();
			const failed = runs.some((r) => /FAIL|ABORT/i.test(r.event_type ?? ''));
			const layer = dsDepth.get(n.id) ?? 0;
			const row = (perLayer[layer] = (perLayer[layer] ?? 0) + 1) - 1;
			return {
				id: n.id,
				type: 'medallion' as const,
				position: prev.get(n.id)?.position ?? { x: 30 + layer * 300, y: 40 + row * 130 },
				data: {
					id: n.id,
					// Color/icon: keep the medallion ramp for the known stage tables, else key by depth.
					layer: LAYER[n.id] ?? Math.min(layer, 4),
					source_uri: n.source_uri,
					tags: n.tags ?? [],
					versions,
					failed,
					selected: false,
					runState: runStateByDataset[n.id] ?? null,
				},
			};
		});
		edges = store.edges.map((e) => ({
			id: `${e.target}->${e.source}`,
			source: e.target,
			target: e.source,
			animated: true,
			type: 'smoothstep',
		}));
		buildMs = Math.round((performance.now() - t0) * 10) / 10;
	});

	// A node click opens the detail page (Marquez parity): dataset node → dataset detail,
	// job node → job detail.
	function openNode(e: unknown) {
		const ev = e as { node?: { id: string }; targetNode?: { id: string } };
		const id = ev.node?.id ?? ev.targetNode?.id ?? null;
		if (!id) return;
		const kind = graphView === 'jobs' ? 'jobs' : 'datasets';
		goto(`${base}/${kind}/${encodeURIComponent(id)}`);
	}
</script>

<svelte:head><title>Lineage graph · lance</title></svelte:head>

<div class="app">
	<header {@attach stagger({ each: 0.08 })}>
		<h1>Graph <span class="sub">dataset + job lineage</span></h1>
		<p class="explain">
			The derivation DAG the OpenLineage feed builds — click a node to open its detail page.
		</p>
		<div class="status">
			<Radio size={13} class={store.online ? 'live-ic on' : 'live-ic'} />
			<span class="state-word" class:live={store.online}>{status}</span>
			<span class="sep">·</span>
			<span class="num mono" {@attach countUp(datasetCount)}>0</span> datasets
			{#if store.capped}<span class="capped">first {store.nodes.length} of {store.total}</span>{/if}
			{#if store.lastUpdated}<span class="sep">·</span>
				<span class="ts">{store.lastUpdated}</span>{/if}
			<span class="sep">·</span>
			<span class="perf mono" title="last layout build">{buildMs}ms</span>
		</div>
	</header>

	<section class="graph">
		<SvelteFlow bind:nodes bind:edges {nodeTypes} colorMode="dark" fitView onnodeclick={openNode}>
			<Background variant={BackgroundVariant.Dots} gap={16} />
			<Controls />
			<MiniMap
				pannable
				zoomable
				nodeColor="#6aa9ff"
				maskColor="rgba(11,15,23,0.72)"
				bgColor="#0e141d"
			/>
			<FlowAutoFit trigger={fitKey} />
			<Panel position="top-left">
				<div class="viewtoggle" role="tablist" aria-label="Graph view">
					<button
						class="vt"
						class:on={graphView === 'datasets'}
						role="tab"
						aria-selected={graphView === 'datasets'}
						onclick={() => (graphView = 'datasets')}
					>
						<Boxes size={13} /> Datasets
					</button>
					<button
						class="vt"
						class:on={graphView === 'jobs'}
						role="tab"
						aria-selected={graphView === 'jobs'}
						onclick={() => (graphView = 'jobs')}
					>
						<Cpu size={13} /> Jobs
					</button>
				</div>
			</Panel>
		</SvelteFlow>
		{#if store.settled && store.online && nodes.length === 0}
			<div class="empty">
				<b>No lineage yet.</b><br />
				Datasets and jobs appear here as pipelines emit OpenLineage events; browse the
				<a href="{base}/datasets">Datasets</a> view for the governed catalog.
			</div>
		{:else if store.settled && !store.online && nodes.length === 0}
			<div class="empty">
				<b>Lineage service unreachable.</b><br />
				Retrying every few seconds — the graph renders as soon as the feed answers.
			</div>
		{/if}
	</section>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
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
	.capped {
		color: var(--faint);
		font-size: 11px;
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
	.perf {
		color: var(--faint);
		font-size: 10px;
	}
	:global(.live-ic) {
		color: var(--mut);
		transition: color 0.3s var(--ease);
	}
	:global(.live-ic.on) {
		color: var(--ok);
	}
	.graph {
		position: relative;
		flex: 1 1 0;
		min-height: 0;
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
	.empty a {
		color: var(--ink);
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
</style>
