import { describe, expect, it } from 'vitest';
import { navMain } from '../src/lib/shell/nav-config';

// The 4 lance micro-frontend domains — the shared sidebar renders these in every zone.
describe('navMain', () => {
	const nav = navMain();

	it('exposes exactly the 4 lance domains, in order', () => {
		expect(nav.map((d) => d.title)).toEqual(['Data', 'Lineage', 'Models', 'Admin']);
		expect(nav.map((d) => d.href)).toEqual(['/data', '/lineage', '/models', '/admin']);
	});

	it('gives every domain a collapsible leaf set with domain-relative hrefs', () => {
		for (const domain of nav) {
			expect(domain.items?.length).toBeGreaterThan(0);
			for (const leaf of domain.items ?? []) {
				expect(leaf.href.startsWith(domain.href)).toBe(true);
			}
		}
	});

	it('active-match: a domain matches its own path and any nested path, not a sibling', () => {
		const data = nav.find((d) => d.title === 'Data')!;
		expect(data.match('/data')).toBe(true);
		expect(data.match('/data/tables')).toBe(true);
		expect(data.match('/data/tables/db$t')).toBe(true);
		expect(data.match('/lineage')).toBe(false);
		expect(data.match('/')).toBe(false);
	});

	it('active-match: a leaf matches its exact route (+ nested) only', () => {
		const tables = navMain()
			.find((d) => d.title === 'Data')!
			.items!.find((l) => l.title === 'Tables')!;
		expect(tables.match('/data/tables')).toBe(true);
		expect(tables.match('/data/tables/x')).toBe(true);
		expect(tables.match('/data/namespaces')).toBe(false);
	});

	it('active-match: a root leaf (href == domain href) matches ONLY its exact path, not siblings', () => {
		// Registry (=/models) and Graph (=/lineage) sit at their zone root; `seg` would keep them lit on
		// every sub-route (e.g. Registry on /models/pipeline). They must match exactly so only one leaf
		// highlights per route.
		const registry = navMain()
			.find((d) => d.title === 'Models')!
			.items!.find((l) => l.title === 'Registry')!;
		expect(registry.match('/models')).toBe(true);
		expect(registry.match('/models/pipeline')).toBe(false);
		expect(registry.match('/models/experiments')).toBe(false);

		const graph = navMain()
			.find((d) => d.title === 'Lineage')!
			.items!.find((l) => l.title === 'Graph')!;
		expect(graph.match('/lineage')).toBe(true);
		expect(graph.match('/lineage/runs')).toBe(false);
	});

	it('active-match: tolerates a trailing slash on the zone root (base-path pathname)', () => {
		// A zone served under a base path reports its root as `/models/` (trailing slash). The root leaf
		// and its domain must still match, or nothing lights up on the landing.
		const models = navMain().find((d) => d.title === 'Models')!;
		const registry = models.items!.find((l) => l.title === 'Registry')!;
		expect(models.match('/models/')).toBe(true);
		expect(registry.match('/models/')).toBe(true);
		expect(registry.match('/models/pipeline')).toBe(false);
	});
});
