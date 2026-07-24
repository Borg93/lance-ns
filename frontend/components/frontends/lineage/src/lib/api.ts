import type {
	ColumnGraph,
	Creator,
	DatasetGovernance,
	DatasetSchema,
	ColumnNeighbors,
	Datasets,
	EstateGraph,
	Events,
	Jobs,
	LineageGraph,
	Namespaces,
	Neighbors,
	Producers,
	Readers,
	RunInputs,
	Runs,
	SearchResults,
} from './types';

import { FETCH_TIMEOUT_MS, bffPath, requestJSON, timeoutSignal } from './http';

async function getJSON<T>(path: string): Promise<T | null> {
	try {
		const res = await fetch(bffPath(`/api/${path}`), { signal: timeoutSignal(FETCH_TIMEOUT_MS) });
		if (!res.ok) return null;
		return (await res.json()) as T;
	} catch {
		return null;
	}
}

const enc = encodeURIComponent;

export const fetchGraph = (name: string) => getJSON<LineageGraph>(`datasets/${enc(name)}/graph`);
// The bulk estate read: every visible node + DERIVED_FROM edge (with per-node version/failed
// rollups) in ONE request — replaces the per-dataset /producers + /graph fan-out that cost
// hundreds of requests per refresh at estate scale.
export const fetchEstateGraph = (limit: number) => getJSON<EstateGraph>(`graph?limit=${limit}`);
export const fetchProducers = (name: string) =>
	getJSON<Producers>(`datasets/${enc(name)}/producers`);
// The read-audit query (#41): who READ this dataset. Owner-gated (stricter than /producers), so it's
// status-aware — a 403 ("owner access required") must read differently from offline or an empty log.
export const fetchReaders = (name: string) =>
	requestJSON<Readers>('/api', `datasets/${enc(name)}/readers`);
export const fetchEvents = (opts: { after?: number; limit?: number; summary?: boolean } = {}) => {
	const p = new URLSearchParams();
	if (opts.after) p.set('after', String(opts.after));
	if (opts.limit) p.set('limit', String(opts.limit));
	if (opts.summary) p.set('summary', 'true');
	const qs = p.toString();
	return getJSON<Events>(`events${qs ? `?${qs}` : ''}`);
};
export const fetchRuns = () => getJSON<Runs>('runs');
// Direct dataset-level neighbors (the backend's own /upstream + /downstream reads) — what a dataset
// was derived from / what derives from it, without assembling the whole subgraph client-side.
export const fetchUpstream = (name: string) => getJSON<Neighbors>(`datasets/${enc(name)}/upstream`);
export const fetchDownstream = (name: string) =>
	getJSON<Neighbors>(`datasets/${enc(name)}/downstream`);
// The inputs a run consumed, each with the version it PINNED (#115 D1 reproducibility) — "which exact
// feature versions produced this output". Fetched per-run on demand (kept off the hot /runs board to
// avoid N+1), so it's a plain read: null on any error, an empty list when the run pinned nothing.
export const fetchRunInputs = (runId: string) => getJSON<RunInputs>(`runs/${enc(runId)}/inputs`);
export const fetchDatasets = (opts: { namespace?: string; tag?: string; limit?: number } = {}) => {
	const p = new URLSearchParams();
	if (opts.namespace) p.set('namespace', opts.namespace);
	if (opts.tag) p.set('tag', opts.tag);
	if (opts.limit) p.set('limit', String(opts.limit));
	const qs = p.toString();
	return getJSON<Datasets>(`datasets${qs ? `?${qs}` : ''}`);
};
export const fetchSearch = (q: string, limit = 10) =>
	getJSON<SearchResults>(`search?q=${enc(q)}&limit=${limit}`);
export const fetchJobs = () => getJSON<Jobs>('jobs');
export const fetchNamespaces = () => getJSON<Namespaces>('namespaces');
export const fetchColumnGraph = (name: string) =>
	getJSON<ColumnGraph>(`datasets/${enc(name)}/columns`);
// Who ORIGINATED a dataset — the verified catalog principal recorded at create time (provenance, not
// "who wrote the latest version"). Reader-gated like the rest of the dataset reads.
export const fetchCreator = (name: string) => getJSON<Creator>(`datasets/${enc(name)}/creator`);
// The persisted column schema for a dataset AT a given Lance version — time-travel (#24). Omit version
// for the latest. Reader-gated. The per-version schema rides the WROTE edge, so this answers "what did
// this dataset's columns look like at version N".
export const fetchSchema = (name: string, version?: number) =>
	getJSON<DatasetSchema>(
		`datasets/${enc(name)}/schema${version === undefined ? '' : `?version=${version}`}`,
	);
// Per-FIELD provenance (upstream) / impact (downstream) — the field-level analogue of the dataset
// graph's neighbors, gated by require_metadata_access (a GET read → served through the read-only proxy).
export const fetchColumnUpstream = (name: string, field: string) =>
	getJSON<ColumnNeighbors>(`datasets/${enc(name)}/columns/${enc(field)}/upstream`);
export const fetchColumnDownstream = (name: string, field: string) =>
	getJSON<ColumnNeighbors>(`datasets/${enc(name)}/columns/${enc(field)}/downstream`);

// Status-aware list reads for the DataTable pages — a governed stack without a session must render
// "sign in" (401), not the same empty state as an open stack with no data (the TableRegistry pattern).
export const listDatasets = () => requestJSON<Datasets>('/api', 'datasets?limit=500');
export const listJobs = () => requestJSON<Jobs>('/api', 'jobs');
export const listRuns = () => requestJSON<Runs>('/api', 'runs');

// Governance metadata (#49) — the writes need the status (401 sign-in vs 403 rung-denial vs offline),
// so they use the shared status-aware helper instead of getJSON's null-on-error.
const writeJSON = <T>(path: string, init: RequestInit) => requestJSON<T>('/api', path, init);

export const fetchGovernance = (name: string) =>
	getJSON<DatasetGovernance>(`datasets/${enc(name)}/governance`);
export const addDatasetTag = (name: string, tag: string) =>
	writeJSON<DatasetGovernance>(`datasets/${enc(name)}/tags/${enc(tag)}`, { method: 'PUT' });
export const removeDatasetTag = (name: string, tag: string) =>
	writeJSON<DatasetGovernance>(`datasets/${enc(name)}/tags/${enc(tag)}`, { method: 'DELETE' });
export const setDatasetDescription = (name: string, description: string) =>
	writeJSON<DatasetGovernance>(`datasets/${enc(name)}/description`, {
		method: 'PUT',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ description }),
	});
