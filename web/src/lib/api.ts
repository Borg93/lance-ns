import type { DemoDatasets, Events, LineageGraph, Producers, Runs } from './types';

async function getJSON<T>(path: string): Promise<T | null> {
	try {
		const res = await fetch(`/api/${path}`);
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
export const fetchEvents = () => getJSON<Events>('events');
export const fetchDemo = () => getJSON<DemoDatasets>('demo/datasets');
export const fetchRuns = () => getJSON<Runs>('runs');
