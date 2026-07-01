import {
	fetchColumnGraph,
	fetchDatasets,
	fetchDemo,
	fetchEvents,
	fetchGraph,
	fetchProducers,
	fetchRuns
} from './api';
import {
	KNOWN,
	type ColumnGraph,
	type DatasetSummary,
	type DemoDataset,
	type EventRecord,
	type GraphEdge,
	type GraphNode,
	type ProducerInfo,
	type RunStatus
} from './types';

/** Live medallion state, polled from the lineage service. Svelte 5 runes in a class. */
export class LineageState {
	nodes = $state<GraphNode[]>([]);
	edges = $state<GraphEdge[]>([]);
	producers = $state<Record<string, ProducerInfo[]>>({});
	events = $state<EventRecord[]>([]);
	datasets = $state<DemoDataset[]>([]);
	catalog = $state<DatasetSummary[]>([]);
	runs = $state<RunStatus[]>([]);
	lastUpdated = $state('');
	online = $state(false);
	selected = $state<string | null>(null);
	columnGraph = $state<ColumnGraph | null>(null);

	/** Load the column-level lineage subgraph for one dataset (the field-to-field view). */
	async loadColumns(name: string): Promise<void> {
		this.columnGraph = await fetchColumnGraph(name);
	}

	async poll(): Promise<void> {
		// Discover the datasets to render from the governed /datasets catalog (GOAL 4 A1) rather than a
		// hardcoded list; fall back to the known medallion names when discovery is empty/unavailable so the
		// demo still renders offline.
		const cat = await fetchDatasets({ limit: 500 });
		this.catalog = cat?.datasets ?? [];
		const names = this.catalog.length ? this.catalog.map((d) => d.name) : [...KNOWN];

		const producers: Record<string, ProducerInfo[]> = {};
		const present: string[] = [];
		for (const id of names) {
			const p = await fetchProducers(id);
			producers[id] = p?.producers ?? [];
			if (producers[id].length) present.push(id);
		}

		const nodeMap = new Map<string, GraphNode>();
		const edgeSet = new Set<string>();
		for (const id of present) {
			const g = await fetchGraph(id);
			if (!g) continue;
			for (const n of g.nodes) nodeMap.set(n.id, n);
			for (const e of g.edges) edgeSet.add(`${e.source}|${e.target}`);
		}

		const events = await fetchEvents();
		const demo = await fetchDemo();
		const runs = await fetchRuns();

		this.runs = runs?.runs ?? [];
		this.producers = producers;
		this.nodes = [...nodeMap.values()];
		this.edges = [...edgeSet].map((key) => {
			const [source, target] = key.split('|');
			return { source, target, kind: 'derived_from' };
		});
		this.events = events?.events ?? [];
		this.datasets = demo?.datasets ?? [];
		this.online = events !== null || present.length > 0;
		this.lastUpdated = new Date().toLocaleTimeString();
	}
}
