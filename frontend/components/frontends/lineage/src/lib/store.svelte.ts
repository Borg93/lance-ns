import { fetchDatasets, fetchEvents, fetchGraph, fetchProducers, fetchRuns } from './api';
import type { EventRecord, GraphEdge, GraphNode, ProducerInfo, RunStatus } from './types';

/** Concurrency cap for the per-dataset fan-outs — an unbounded Promise.all would fire them ALL at
 * once every poll tick (and the browser's per-host connection queue would eat into each request's 8s
 * timeout while still queued — review 2026-07-11). Batches of 8 keep the fan-out concurrent but
 * bounded. */
const POOL = 8;

/** Hard cap on the datasets the DAG explorer assembles per tick. The graph is a per-dataset
 * /producers + /graph fan-out; an uncapped catalog (≤500) would mean hundreds of requests AND a
 * SvelteFlow canvas too dense to read — the full estate belongs to the paginated Datasets table,
 * not the canvas. The header shows `capped` honestly when the estate exceeds the window. */
const MAX_GRAPH = 60;

/** How many recent events feed the jobs plane (job identity/state/edges are folded from these). */
const EVENTS_WINDOW = 200;

/** Live lineage state for the DAG explorer, polled from the lineage service. Svelte 5 runes in a
 * class. List pages (Datasets / Jobs / Runs) fetch their own endpoints — this store only carries
 * what the graph view renders. */
export class LineageState {
	nodes = $state<GraphNode[]>([]);
	edges = $state<GraphEdge[]>([]);
	producers = $state<Record<string, ProducerInfo[]>>({});
	events = $state<EventRecord[]>([]);
	runs = $state<RunStatus[]>([]);
	/** Total datasets the governed catalog reports (may exceed the MAX_GRAPH window). */
	total = $state(0);
	/** True when the estate is larger than the graph window — the header says so honestly. */
	capped = $state(false);
	/** True once the FIRST poll settled (success or failure) — before that the UI says "connecting",
	 * never "waiting/offline" (the old header claimed WAITING while the canvas showed datasets). */
	settled = $state(false);
	online = $state(false);
	lastUpdated = $state('');

	/** Overlap guard: a slow tick must not stack behind the poll interval (§2 perf, 2026-07-11). */
	#polling = false;

	async poll(): Promise<void> {
		if (this.#polling) return;
		this.#polling = true;
		try {
			// Discover the datasets to render from the governed /datasets catalog. HARD-FAILURE GUARD
			// (audit B1): `getJSON` maps timeout / 4xx / 5xx / network error to null — indistinguishable
			// from "empty". A failed discovery PRESERVES the last good state and reports offline; it
			// never blanks the canvas (or destroys dragged node positions) on a blip.
			const cat = await fetchDatasets({ limit: MAX_GRAPH });
			if (cat === null) {
				this.online = false;
				return;
			}
			this.total = cat.total ?? cat.datasets.length;
			this.capped = this.total > cat.datasets.length;
			const names = cat.datasets.map((d) => d.name);

			const producers: Record<string, ProducerInfo[]> = {};
			const producerLists = await inPools(names, (id) => fetchProducers(id));
			const present: string[] = [];
			names.forEach((id, i) => {
				producers[id] = producerLists[i]?.producers ?? [];
				if (producers[id].length) present.push(id);
			});

			const nodeMap = new Map<string, GraphNode>();
			const edgeSet = new Set<string>();
			const [graphs, events, runs] = await Promise.all([
				inPools(present, (id) => fetchGraph(id)),
				fetchEvents({ limit: EVENTS_WINDOW, summary: true }),
				fetchRuns(),
			]);
			for (const g of graphs) {
				if (!g) continue;
				for (const n of g.nodes) nodeMap.set(n.id, n);
				for (const e of g.edges) edgeSet.add(`${e.source}|${e.target}`);
			}

			// Assign only what actually RESOLVED (audit B1). A null sub-fetch means "this slice failed
			// this tick", NOT "this slice is now empty" — a transient blip must not erase live state.
			if (runs) this.runs = runs.runs ?? [];
			if (events) this.events = events.events ?? [];

			// The graph is rebuilt from the per-dataset fan-out. Replace it only if at least one graph
			// fetch succeeded — otherwise every graph call failed and an empty nodeMap would wipe the
			// canvas (and the dragged positions) on a blip.
			const anyGraph = graphs.some((g) => g !== null);
			if (anyGraph || present.length === 0) {
				this.producers = producers;
				this.nodes = [...nodeMap.values()];
				this.edges = [...edgeSet].map((key) => {
					// key is `${source}|${target}` (always two parts); `?? ''` satisfies
					// noUncheckedIndexedAccess (the zone's tsconfig) — the empty fallback is unreachable.
					const [source = '', target = ''] = key.split('|');
					return { source, target, kind: 'derived_from' };
				});
			}

			this.online = true;
			this.lastUpdated = new Date().toLocaleTimeString();
		} finally {
			this.settled = true;
			this.#polling = false;
		}
	}
}

async function inPools<T, R>(items: T[], fn: (item: T) => Promise<R>): Promise<R[]> {
	const out: R[] = [];
	for (let i = 0; i < items.length; i += POOL) {
		out.push(...(await Promise.all(items.slice(i, i + POOL).map(fn))));
	}
	return out;
}
