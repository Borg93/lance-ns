// Mirrors the lineage service response schemas (lineage/schemas.py).

export interface GraphNode {
	id: string;
	namespace?: string | null;
	kind: string;
	source_uri?: string | null;
	tags: string[];
}

export interface GraphEdge {
	source: string;
	target: string;
	kind: string;
}

export interface LineageGraph {
	root: string;
	nodes: GraphNode[];
	edges: GraphEdge[];
}

export interface ProducerInfo {
	run_id: string;
	author?: string | null;
	event_time?: string | null;
	event_type?: string | null;
	dataset_version?: string | null;
	producer?: string | null;
	error_message?: string | null;
}

export interface Producers {
	dataset: string;
	producers: ProducerInfo[];
}

export interface EventRecord {
	seq: number;
	event_type?: string | null;
	event_time?: string | null;
	job?: string | null;
	author?: string | null;
	inputs: string[];
	outputs: string[];
	event: Record<string, unknown>;
}

export interface Events {
	events: EventRecord[];
}

export interface DemoField {
	name: string;
	type: string;
}

export interface DemoVersion {
	version: number;
	timestamp?: string | null;
	fields: DemoField[];
}

export interface DemoDataset {
	name: string;
	uri: string;
	exists: boolean;
	current_version?: number | null;
	row_count?: number | null;
	versions: DemoVersion[];
	lineage_jsonb?: Record<string, unknown> | null;
	error?: string | null;
}

export interface DemoDatasets {
	datasets: DemoDataset[];
}

// The medallion datasets, in flow order (raw -> bronze -> silver -> gold).
export const KNOWN = ['raw_events', 'bronze$events', 'silver$features', 'gold$catalog'] as const;
export const LAYER: Record<string, number> = {
	raw_events: 0,
	'bronze$events': 1,
	'silver$features': 2,
	'gold$catalog': 3
};
