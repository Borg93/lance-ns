import { describe, it, expect } from 'vitest';
import { pathCrumbs, projectFromHost } from '../src/lib/shell/breadcrumb.js';

// Project-first IA via HOST: the project is the request host, so the pathname
// carries only the domain + in-domain trail. Every path segment is a crumb (the
// DOMAIN is the first crumb, never the project); the project is the breadcrumb
// root and comes from the host, not the path.
describe('pathCrumbs', () => {
	it('keeps the domain as the first crumb on a nested path', () => {
		// /compute/jobs -> Compute > Jobs (the domain must NOT be dropped)
		expect(pathCrumbs('/compute/jobs')).toEqual([
			{ id: 'compute', label: 'compute', href: '/compute' },
			{ id: 'compute/jobs', label: 'jobs', href: '/compute/jobs' },
		]);
	});

	it('yields a single domain crumb for a bare domain landing', () => {
		// /overview -> Overview (previously produced an empty trail)
		expect(pathCrumbs('/overview')).toEqual([
			{ id: 'overview', label: 'overview', href: '/overview' },
		]);
	});

	it('humanises dashed segments and keeps repeated segments unique', () => {
		expect(pathCrumbs('/compute/api-docs')).toEqual([
			{ id: 'compute', label: 'compute', href: '/compute' },
			{ id: 'compute/api-docs', label: 'api docs', href: '/compute/api-docs' },
		]);
		expect(pathCrumbs('/studio/studio').map((c) => c.id)).toEqual(['studio', 'studio/studio']);
	});

	it('percent-decodes a segment for the label but keeps the href encoded', () => {
		// A table/dataset id reaches the URL encoded (silver$features -> silver%24features);
		// the crumb must READ as the id, while still linking to the path that resolves.
		const crumbs = pathCrumbs('/lineage/datasets/silver%24features');
		expect(crumbs.at(-1)).toEqual({
			id: 'lineage/datasets/silver%24features',
			label: 'silver$features',
			href: '/lineage/datasets/silver%24features',
		});
	});

	it('falls back to the raw segment when the escape is malformed', () => {
		// decodeURIComponent throws on a lone '%': the trail must still render.
		expect(pathCrumbs('/data/100%').at(-1)?.label).toBe('100%');
	});

	it('returns no crumbs for the root path', () => {
		expect(pathCrumbs('/')).toEqual([]);
		expect(pathCrumbs('')).toEqual([]);
	});
});

describe('projectFromHost', () => {
	it('reads the project label from a real subdomain host', () => {
		expect(projectFromHost('demo.localhost')).toBe('demo');
		expect(projectFromHost('demo.rask.example.com')).toBe('demo');
	});

	it('has no project on a bare host', () => {
		expect(projectFromHost('localhost')).toBeNull();
	});

	it('has no project on an IPv4 host (first label is an octet, not a project)', () => {
		expect(projectFromHost('127.0.0.1')).toBeNull();
	});
});
