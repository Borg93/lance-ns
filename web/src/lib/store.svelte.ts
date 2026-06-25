import { fetchDemo, fetchEvents, fetchGraph, fetchProducers, fetchRuns } from './api';
import { KNOWN, type DemoDataset, type EventRecord, type GraphEdge, type GraphNode, type ProducerInfo, type RunStatus } from './types';

/** Live medallion state, polled from the lineage service. Svelte 5 runes in a class. */
export class LineageState {
	nodes = $state<GraphNode[]>([]);
	edges = $state<GraphEdge[]>([]);
	producers = $state<Record<string, ProducerInfo[]>>({});
	events = $state<EventRecord[]>([]);
	datasets = $state<DemoDataset[]>([]);
	runs = $state<RunStatus[]>([]);
	lastUpdated = $state('');
	online = $state(false);
	selected = $state<string | null>(null);

	async poll(): Promise<void> {
		const producers: Record<string, ProducerInfo[]> = {};
		const present: string[] = [];
		for (const id of KNOWN) {
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
