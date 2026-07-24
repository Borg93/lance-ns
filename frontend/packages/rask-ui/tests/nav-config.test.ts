import { describe, expect, it } from 'vitest';
import { exact, norm, seg, topNav, under, zoneOf } from '../src/lib/shell/nav-config';

// The top-navbar IA (one entry per microfrontend zone, admin entries estate-gated) + the shared
// matchers every zone builds its ZoneNav sidebar config with.
describe('topNav', () => {
	it('exposes the base zones, in order, for a non-admin (fail-closed)', () => {
		expect(topNav(false).map((e) => e.title)).toEqual([
			'Home',
			'Data',
			'Lineage',
			'Models',
			'Media',
			'Annotator',
		]);
		expect(topNav(false).map((e) => e.href)).toEqual([
			'/',
			'/data',
			'/lineage',
			'/models',
			'/media',
			'/annotator',
		]);
	});

	it('appends Admin only for an estate admin', () => {
		const titles = topNav(true).map((e) => e.title);
		expect(titles).toEqual(['Home', 'Data', 'Lineage', 'Models', 'Media', 'Annotator', 'Admin']);
		expect(topNav(true).find((e) => e.title === 'Admin')?.href).toBe('/admin');
	});

	it('never exposes Access as a navbar entry — it lives inside the admin zone', () => {
		// 4b2af0e folded Access into the admin zone's own sidebar, so Admin owns the whole
		// /admin subtree up here. Asserted for BOTH identities so a future regression that
		// re-adds it (for either) is caught.
		expect(topNav(false).map((e) => e.title)).not.toContain('Access');
		expect(topNav(true).map((e) => e.title)).not.toContain('Access');
	});

	it('active-match: a zone matches its own path and any nested path, not a sibling or root', () => {
		const data = topNav(false).find((e) => e.title === 'Data')!;
		expect(data.match('/data')).toBe(true);
		expect(data.match('/data/tables/db$t')).toBe(true);
		expect(data.match('/lineage')).toBe(false);
		expect(data.match('/')).toBe(false);
	});

	it('active-match: Home matches ONLY the origin root (trailing-slash tolerant)', () => {
		const home = topNav(false).find((e) => e.title === 'Home')!;
		expect(home.match('/')).toBe(true);
		expect(home.match('/data')).toBe(false);
	});

	it('carries panel sub-areas for the zones that have them, plain links for the rest', () => {
		const byTitle = Object.fromEntries(topNav(true).map((e) => [e.title, e]));
		expect(byTitle.Data!.items?.map((i) => i.title)).toEqual([
			'Projects',
			'Tables',
			'Namespaces',
			'Warehouses',
		]);
		expect(byTitle.Lineage!.items?.map((i) => i.title)).toEqual([
			'Datasets',
			'Jobs',
			'Runs',
			'Columns',
			'Graph',
		]);
		expect(byTitle.Media!.items?.map((i) => i.title)).toEqual([
			'Search',
			'Atlas',
			'Tree',
			'Graph',
			'Workflow',
		]);
		expect(byTitle.Admin!.items?.map((i) => i.title)).toEqual([
			'Tenants',
			'Audit',
			'Streams',
			'DLQ',
			'Events',
			'Access',
		]);
		// A zone with a single surface stays a plain link — no one-row dropdown.
		for (const title of ['Home', 'Models', 'Annotator']) {
			expect(byTitle[title]!.items).toBeUndefined();
		}
	});

	it('every panel row is an absolute path inside its own zone, and each carries a description', () => {
		for (const entry of topNav(true)) {
			for (const item of entry.items ?? []) {
				expect(item.href.startsWith(entry.href)).toBe(true);
				expect(item.description.length).toBeGreaterThan(0);
			}
		}
	});

	it('Access is a row of the Admin panel only — never a navbar entry of its own', () => {
		const admin = topNav(true).find((e) => e.title === 'Admin')!;
		expect(admin.items?.find((i) => i.title === 'Access')?.href).toBe('/admin/access');
		// …and a non-admin gets no panel carrying it at all.
		expect(
			topNav(false)
				.flatMap((e) => e.items ?? [])
				.map((i) => i.href),
		).not.toContain('/admin/access');
	});

	it('active-match: Admin covers the WHOLE /admin subtree, /admin/access included', () => {
		const admin = topNav(true).find((e) => e.title === 'Admin')!;
		expect(admin.match('/admin')).toBe(true);
		expect(admin.match('/admin/audit')).toBe(true);
		expect(admin.match('/admin/access')).toBe(true);
		expect(admin.match('/admin/access/x')).toBe(true);
		expect(admin.match('/data')).toBe(false);
	});
});

describe('ZoneNav matchers', () => {
	it('seg: matches the exact route and anything nested under it', () => {
		const m = seg('/data/tables');
		expect(m('/data/tables')).toBe(true);
		expect(m('/data/tables/x')).toBe(true);
		expect(m('/data/namespaces')).toBe(false);
	});

	it('exact: matches only its own path — the root-leaf (href == zone href) case', () => {
		// Registry (=/models) sits at its zone root; `seg` would keep it lit on every sub-route.
		const m = exact('/models');
		expect(m('/models')).toBe(true);
		expect(m('/models/pipeline')).toBe(false);
	});

	it('norm + matchers tolerate the base-path trailing slash on a zone root', () => {
		// A zone served under a base path reports its root as `/models/` (trailing slash).
		expect(norm('/models/')).toBe('/models');
		expect(norm('/')).toBe('/');
		expect(exact('/models')('/models/')).toBe(true);
		expect(under('/models')('/models/')).toBe(true);
	});

	it('zoneOf: first path segment, with the home zone at the empty key', () => {
		expect(zoneOf('/data/tables')).toBe('data');
		expect(zoneOf('/admin')).toBe('admin');
		expect(zoneOf('/')).toBe('');
		expect(zoneOf('')).toBe('');
	});
});
