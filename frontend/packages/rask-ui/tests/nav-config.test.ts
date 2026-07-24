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

	it('appends Admin + Access only for an estate admin', () => {
		const titles = topNav(true).map((e) => e.title);
		expect(titles).toEqual([
			'Home',
			'Data',
			'Lineage',
			'Models',
			'Media',
			'Annotator',
			'Admin',
			'Access',
		]);
		expect(topNav(true).find((e) => e.title === 'Access')?.href).toBe('/admin/access');
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

	it('active-match: Access owns /admin/access and Admin excludes it (one lit entry per route)', () => {
		const admin = topNav(true).find((e) => e.title === 'Admin')!;
		const access = topNav(true).find((e) => e.title === 'Access')!;
		expect(admin.match('/admin')).toBe(true);
		expect(admin.match('/admin/audit')).toBe(true);
		expect(admin.match('/admin/access')).toBe(false);
		expect(access.match('/admin/access')).toBe(true);
		expect(access.match('/admin/access/x')).toBe(true);
		expect(access.match('/admin')).toBe(false);
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
