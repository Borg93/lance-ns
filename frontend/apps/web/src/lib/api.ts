import type {
	ColumnGraph,
	ColumnNeighbors,
	Datasets,
	DemoDatasets,
	Events,
	Jobs,
	LineageGraph,
	Namespaces,
	Producers,
	Runs,
	SearchResults,
} from "./types";

import { FETCH_TIMEOUT_MS, timeoutSignal } from "./http";

async function getJSON<T>(path: string): Promise<T | null> {
	try {
		const res = await fetch(`/api/${path}`, { signal: timeoutSignal(FETCH_TIMEOUT_MS) });
		if (!res.ok) return null;
		return (await res.json()) as T;
	} catch {
		return null;
	}
}

const enc = encodeURIComponent;

export const fetchGraph = (name: string) => getJSON<LineageGraph>(`datasets/${enc(name)}/graph`);
export const fetchProducers = (name: string) =>
	getJSON<Producers>(`datasets/${enc(name)}/producers`);
export const fetchEvents = (opts: { after?: number; limit?: number; summary?: boolean } = {}) => {
	const p = new URLSearchParams();
	if (opts.after) p.set("after", String(opts.after));
	if (opts.limit) p.set("limit", String(opts.limit));
	if (opts.summary) p.set("summary", "true");
	const qs = p.toString();
	return getJSON<Events>(`events${qs ? `?${qs}` : ""}`);
};
export const fetchDemo = () => getJSON<DemoDatasets>("demo/datasets");
export const fetchRuns = () => getJSON<Runs>("runs");
export const fetchDatasets = (opts: { namespace?: string; tag?: string; limit?: number } = {}) => {
	const p = new URLSearchParams();
	if (opts.namespace) p.set("namespace", opts.namespace);
	if (opts.tag) p.set("tag", opts.tag);
	if (opts.limit) p.set("limit", String(opts.limit));
	const qs = p.toString();
	return getJSON<Datasets>(`datasets${qs ? `?${qs}` : ""}`);
};
export const fetchSearch = (q: string, limit = 10) =>
	getJSON<SearchResults>(`search?q=${enc(q)}&limit=${limit}`);
export const fetchJobs = () => getJSON<Jobs>("jobs");
export const fetchNamespaces = () => getJSON<Namespaces>("namespaces");
export const fetchColumnGraph = (name: string) =>
	getJSON<ColumnGraph>(`datasets/${enc(name)}/columns`);
// Per-FIELD provenance (upstream) / impact (downstream) — the field-level analogue of the dataset
// graph's neighbors, gated by require_metadata_access (a GET read → served through the read-only proxy).
export const fetchColumnUpstream = (name: string, field: string) =>
	getJSON<ColumnNeighbors>(`datasets/${enc(name)}/columns/${enc(field)}/upstream`);
export const fetchColumnDownstream = (name: string, field: string) =>
	getJSON<ColumnNeighbors>(`datasets/${enc(name)}/columns/${enc(field)}/downstream`);
