import type { ColumnGraph, Datasets, DemoDatasets, Events, LineageGraph, Producers, Runs } from './types';

/** Per-request timeout — a hung backend must not stack poll ticks (§2 perf, 2026-07-11). */
const FETCH_TIMEOUT_MS = 8000;

// AbortSignal.timeout needs Safari 16+/Chrome 103+; vite transpiles syntax, not APIs — on an older
// browser the missing function would throw inside getJSON's catch and the app would silently render
// permanently "offline". Feature-detect with an AbortController fallback (review 2026-07-11).
function timeoutSignal(ms: number): AbortSignal {
	if (typeof AbortSignal.timeout === 'function') return AbortSignal.timeout(ms);
	const controller = new AbortController();
	setTimeout(() => controller.abort(), ms);
	return controller.signal;
}

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

export const fetchGraph = (name: string) =>
	getJSON<LineageGraph>(`datasets/${enc(name)}/graph`);
export const fetchProducers = (name: string) =>
	getJSON<Producers>(`datasets/${enc(name)}/producers`);
export const fetchEvents = (opts: { after?: number; limit?: number; summary?: boolean } = {}) => {
	const p = new URLSearchParams();
	if (opts.after) p.set('after', String(opts.after));
	if (opts.limit) p.set('limit', String(opts.limit));
	if (opts.summary) p.set('summary', 'true');
	const qs = p.toString();
	return getJSON<Events>(`events${qs ? `?${qs}` : ''}`);
};
export const fetchDemo = () => getJSON<DemoDatasets>('demo/datasets');
export const fetchRuns = () => getJSON<Runs>('runs');
export const fetchDatasets = (opts: { namespace?: string; tag?: string; limit?: number } = {}) => {
	const p = new URLSearchParams();
	if (opts.namespace) p.set('namespace', opts.namespace);
	if (opts.tag) p.set('tag', opts.tag);
	if (opts.limit) p.set('limit', String(opts.limit));
	const qs = p.toString();
	return getJSON<Datasets>(`datasets${qs ? `?${qs}` : ''}`);
};
export const fetchColumnGraph = (name: string) =>
	getJSON<ColumnGraph>(`datasets/${enc(name)}/columns`);
