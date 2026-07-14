import {
	fetchColumnDownstream,
	fetchColumnGraph,
	fetchColumnUpstream,
	fetchDatasets,
	fetchDemo,
	fetchEvents,
	fetchGraph,
	fetchJobs,
	fetchNamespaces,
	fetchProducers,
	fetchRuns,
} from "./api";
import {
	KNOWN,
	type ColumnGraph,
	type ColumnNeighbors,
	type DatasetSummary,
	type DemoDataset,
	type EventRecord,
	type JobSummary,
	type GraphEdge,
	type GraphNode,
	type ProducerInfo,
	type RunStatus,
} from "./types";

/** Concurrency cap for the per-dataset fan-outs — the catalog can list up to 500 datasets, and an
 * unbounded Promise.all would fire them ALL at once every 2s tick (and the browser's per-host
 * connection queue would eat into each request's 8s timeout while still queued — review
 * 2026-07-11). Batches of 8 keep the fan-out concurrent but bounded. */
const POOL = 8;

async function inPools<T, R>(items: T[], fn: (item: T) => Promise<R>): Promise<R[]> {
	const out: R[] = [];
	for (let i = 0; i < items.length; i += POOL) {
		out.push(...(await Promise.all(items.slice(i, i + POOL).map(fn))));
	}
	return out;
}

/** Live medallion state, polled from the lineage service. Svelte 5 runes in a class. */
export class LineageState {
	nodes = $state<GraphNode[]>([]);
	edges = $state<GraphEdge[]>([]);
	producers = $state<Record<string, ProducerInfo[]>>({});
	events = $state<EventRecord[]>([]);
	datasets = $state<DemoDataset[]>([]);
	catalog = $state<DatasetSummary[]>([]);
	runs = $state<RunStatus[]>([]);
	jobs = $state<JobSummary[]>([]);
	namespaceList = $state<string[]>([]);
	lastUpdated = $state("");
	online = $state(false);
	selected = $state<string | null>(null);
	columnGraph = $state<ColumnGraph | null>(null);
	/** The field the user clicked in the Columns plane — drives the field-level provenance/impact panel
	 * (#24). Kept separate from ``selected`` (a dataset handle) so a column click never pollutes the
	 * dataset-scoped Details/upstream panels (bug hunt 2026-07-13). */
	selectedColumn = $state<{ dataset: string; field: string } | null>(null);
	columnUpstream = $state<ColumnNeighbors | null>(null);
	columnDownstream = $state<ColumnNeighbors | null>(null);

	/** Overlap guard: a slow tick must not stack behind the 2s interval (§2 perf, 2026-07-11). */
	#polling = false;

	/** Monotonic request id so a slow earlier column fetch can't overwrite a newer dataset's graph. */
	#colReq = 0;
	/** Same latest-wins guard, for the per-FIELD neighbor fetches (a slow earlier field's response must
	 * not overwrite a newer selection's provenance/impact). */
	#fieldReq = 0;

	/** Load the column-level lineage subgraph for one dataset (the field-to-field view). Latest-wins:
	 * only the most recent call's response is applied (guards the async race when the selection changes
	 * mid-flight — bug hunt 2026-07-13). */
	async loadColumns(name: string): Promise<void> {
		const req = ++this.#colReq;
		const graph = await fetchColumnGraph(name);
		if (req === this.#colReq) this.columnGraph = graph;
	}

	/** Load one FIELD's provenance (upstream) + impact (downstream) — the two per-field endpoints (#24).
	 * Mirrors ``loadColumns``'s latest-wins guard so switching the focused column mid-flight can't apply a
	 * stale field's neighbors. */
	async loadColumnNeighbors(name: string, field: string): Promise<void> {
		const req = ++this.#fieldReq;
		const [upstream, downstream] = await Promise.all([
			fetchColumnUpstream(name, field),
			fetchColumnDownstream(name, field),
		]);
		if (req === this.#fieldReq) {
			this.columnUpstream = upstream;
			this.columnDownstream = downstream;
		}
	}

	async poll(): Promise<void> {
		// Overlap guard + per-request timeouts (api.ts): before 2026-07-11 a tick was 1+N+P+3
		// SEQUENTIAL fetches with no timeout, so slow backends stacked ticks unboundedly. Now the
		// per-dataset fan-outs run concurrently (Promise.all) and a tick that is still in flight
		// simply skips the next interval firing.
		if (this.#polling) return;
		this.#polling = true;
		try {
			// Discover the datasets to render from the governed /datasets catalog (GOAL 4 A1) rather
			// than a hardcoded list; fall back to the known medallion names when discovery is
			// empty/unavailable so the demo still renders offline.
			const cat = await fetchDatasets({ limit: 500 });
			this.catalog = cat?.datasets ?? [];
			const names = this.catalog.length ? this.catalog.map((d) => d.name) : [...KNOWN];

			const producers: Record<string, ProducerInfo[]> = {};
			const producerLists = await inPools(names, (id) => fetchProducers(id));
			const present: string[] = [];
			names.forEach((id, i) => {
				producers[id] = producerLists[i]?.producers ?? [];
				if (producers[id].length) present.push(id);
			});

			const nodeMap = new Map<string, GraphNode>();
			const edgeSet = new Set<string>();
			const [graphs, events, demo, runs, jobs, namespaces] = await Promise.all([
				inPools(present, (id) => fetchGraph(id)),
				fetchEvents(),
				fetchDemo(),
				fetchRuns(),
				fetchJobs(),
				fetchNamespaces(),
			]);
			for (const g of graphs) {
				if (!g) continue;
				for (const n of g.nodes) nodeMap.set(n.id, n);
				for (const e of g.edges) edgeSet.add(`${e.source}|${e.target}`);
			}

			this.runs = runs?.runs ?? [];
			this.jobs = jobs?.jobs ?? [];
			this.namespaceList = namespaces?.namespaces ?? [];
			this.producers = producers;
			this.nodes = [...nodeMap.values()];
			this.edges = [...edgeSet].map((key) => {
				const [source, target] = key.split("|");
				return { source, target, kind: "derived_from" };
			});
			this.events = events?.events ?? [];
			this.datasets = demo?.datasets ?? [];
			this.online = events !== null || present.length > 0;
			this.lastUpdated = new Date().toLocaleTimeString();
		} finally {
			this.#polling = false;
		}
	}
}
