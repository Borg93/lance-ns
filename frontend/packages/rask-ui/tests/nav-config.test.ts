import { describe, expect, it } from 'vitest';
import { exact, norm, seg, topNav, under, zoneOf } from '../src/lib/shell/nav-config';

// The top-navbar IA + the shared matchers every zone builds its ZoneNav sidebar config with.
// The bar groups by DOMAIN, not by zone, and since the merge the two are no longer the same thing:
// Lakehouse and Lineage are two triggers over ONE zone (/lakehouse), while Media covers two. Lakehouse
// gathers everything that describes or governs the estate (the catalog, the model registry, and —
// estate-admin only — governance and operations), so the bar stays three words while the product
// grows. A new route becomes a row in a panel column, never a new top-level entry.
describe('topNav', () => {
	it('exposes three domain triggers, in order, for a non-admin (fail-closed)', () => {
		expect(topNav(false).map((e) => e.title)).toEqual(['Lakehouse', 'Lineage', 'Media']);
		expect(topNav(false).map((e) => e.href)).toEqual([
			'/lakehouse/data',
			'/lakehouse/lineage',
			'/media',
		]);
	});

	it('keeps the same three triggers for an estate admin — admin earns COLUMNS, not an entry', () => {
		expect(topNav(true).map((e) => e.title)).toEqual(['Lakehouse', 'Lineage', 'Media']);
	});

	it('gates governance + operations behind estate-admin, inside the Lakehouse panel', () => {
		const labels = (admin: boolean) =>
			topNav(admin)
				.find((e) => e.title === 'Lakehouse')!
				.groups!.map((g) => g.label);
		// The governance guarantee, both polarities: a non-admin's panel cannot even name them.
		expect(labels(false)).toEqual(['Catalog', 'Models']);
		expect(labels(true)).toEqual(['Catalog', 'Models', 'Governance', 'Operations']);
	});

	it('never exposes Access as a navbar entry — it is one row of the Governance column', () => {
		expect(topNav(false).map((e) => e.title)).not.toContain('Access');
		expect(topNav(true).map((e) => e.title)).not.toContain('Access');
		const governance = topNav(true)
			.find((e) => e.title === 'Lakehouse')!
			.groups!.find((g) => g.label === 'Governance')!;
		expect(governance.items.find((i) => i.title === 'Access')?.href).toBe(
			'/lakehouse/admin/access',
		);
		// …and a non-admin gets no row carrying it at all, in any panel.
		const nonAdminHrefs = topNav(false).flatMap((e) => [
			...(e.items ?? []),
			...(e.groups ?? []).flatMap((g) => g.items),
		]);
		expect(nonAdminHrefs.map((i) => i.href)).not.toContain('/lakehouse/admin/access');
	});

	it('active-match: Lakehouse lights across every area it covers, EXCEPT lineage', () => {
		// Lakehouse and Lineage now share the /lakehouse prefix, so the Lakehouse trigger has to
		// subtract the lineage subtree or both entries light up together on every lineage route.
		const lakehouse = topNav(true).find((e) => e.title === 'Lakehouse')!;
		for (const p of [
			'/lakehouse/data',
			'/lakehouse/data/tables/db$t',
			'/lakehouse/models',
			'/lakehouse/models/pipeline',
			'/lakehouse/admin/audit',
		]) {
			expect(lakehouse.match(p)).toBe(true);
		}
		expect(lakehouse.match('/lakehouse/lineage')).toBe(false);
		expect(lakehouse.match('/lakehouse/lineage/runs')).toBe(false);
		expect(lakehouse.match('/')).toBe(false);
		expect(lakehouse.match('/media')).toBe(false);
	});

	it('active-match: Lineage claims its own area, and nothing else in the zone', () => {
		const lineage = topNav(true).find((e) => e.title === 'Lineage')!;
		expect(lineage.match('/lakehouse/lineage')).toBe(true);
		expect(lineage.match('/lakehouse/lineage/runs')).toBe(true);
		expect(lineage.match('/lakehouse/data/tables')).toBe(false);
		expect(lineage.match('/lakehouse')).toBe(false);
	});

	it('active-match: Media covers the annotator zone too — Annotate is its panel row', () => {
		const media = topNav(false).find((e) => e.title === 'Media')!;
		expect(media.match('/media')).toBe(true);
		expect(media.match('/annotator')).toBe(true);
		expect(media.items?.find((i) => i.title === 'Annotate')?.href).toBe('/annotator');
	});

	it('carries the expected rows per column', () => {
		const groups = Object.fromEntries(
			topNav(true)
				.find((e) => e.title === 'Lakehouse')!
				.groups!.map((g) => [g.label, g.items.map((i) => i.title)]),
		);
		expect(groups.Catalog).toEqual(['Projects', 'Tables', 'Namespaces', 'Warehouses']);
		expect(groups.Models).toEqual(['Registry', 'Experiments', 'Pipeline']);
		expect(groups.Governance).toEqual(['Access', 'Tenants', 'Audit']);
		expect(groups.Operations).toEqual(['Events', 'Streams', 'DLQ']);
		expect(
			topNav(false)
				.find((e) => e.title === 'Lineage')!
				.items?.map((i) => i.title),
		).toEqual(['Datasets', 'Jobs', 'Runs', 'Columns', 'Graph']);
	});

	it('every panel row is an absolute path with a description', () => {
		for (const entry of topNav(true)) {
			const rows = [...(entry.items ?? []), ...(entry.groups ?? []).flatMap((g) => g.items)];
			expect(rows.length).toBeGreaterThan(0);
			for (const item of rows) {
				expect(item.href.startsWith('/')).toBe(true);
				expect(item.description.length).toBeGreaterThan(0);
			}
		}
	});
});

describe('ZoneNav matchers', () => {
	it('seg: matches the exact route and anything nested under it', () => {
		const m = seg('/lakehouse/data/tables');
		expect(m('/lakehouse/data/tables')).toBe(true);
		expect(m('/lakehouse/data/tables/x')).toBe(true);
		expect(m('/lakehouse/data/namespaces')).toBe(false);
	});

	it('exact: matches only its own path — the root-leaf (href == zone href) case', () => {
		// Registry (=/lakehouse/models) sits at its AREA root; `seg` would keep it lit on every sub-route.
		const m = exact('/lakehouse/models');
		expect(m('/lakehouse/models')).toBe(true);
		expect(m('/lakehouse/models/pipeline')).toBe(false);
	});

	it('norm + matchers tolerate the base-path trailing slash on a zone root', () => {
		// A zone served under a base path reports its root as `/lakehouse/` (trailing slash).
		expect(norm('/lakehouse/')).toBe('/lakehouse');
		expect(norm('/')).toBe('/');
		expect(exact('/lakehouse')('/lakehouse/')).toBe(true);
		expect(under('/lakehouse')('/lakehouse/')).toBe(true);
	});

	it('zoneOf: first path segment, with the home zone at the empty key', () => {
		// The whole estate is ONE zone now, so every lakehouse area shares a zone key — which is what
		// makes a hop between them a soft nav rather than a full document load.
		expect(zoneOf('/lakehouse/data/tables')).toBe('lakehouse');
		expect(zoneOf('/lakehouse/admin')).toBe('lakehouse');
		expect(zoneOf('/media/atlas')).toBe('media');
		expect(zoneOf('/')).toBe('');
		expect(zoneOf('')).toBe('');
	});
});
