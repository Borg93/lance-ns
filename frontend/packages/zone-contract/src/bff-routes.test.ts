import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';
import { FRONTEND_ROOT, zoneDirs } from './manifest';

/**
 * Every BFF route a zone exposes is a hole punched through to a backend, carrying the caller's bearer.
 * A route with no caller is not merely dead code — it is an unauthenticated-by-nobody proxy sitting on
 * the deploy surface. Three had accumulated by inheritance from the standalone lance-media repo:
 * `media` proxied the FULL `/api/annotations/**` and `/api/assist/**` write surfaces while calling
 * neither (only `annotations-client.ts` uses them, and only the annotator imports that), and
 * `annotator` proxied `/api/search` while never searching. That is what "media and annotator share a
 * backend" actually looked like: not a design, an inheritance.
 *
 * So: every route must have a caller, somewhere in the zone or in a package the zone imports.
 */
const grep = (pattern: string): string => {
	try {
		return execFileSync('git', ['grep', '-l', '-e', pattern, '--', 'components', 'packages'], {
			cwd: FRONTEND_ROOT,
			encoding: 'utf8',
		});
	} catch {
		return ''; // git grep exits non-zero on no match
	}
};

/** The route paths a zone serves, as URL prefixes (`/api/annotations/tags`). */
function bffRoutes(zone: string): string[] {
	const out = execFileSync(
		'find',
		[`components/frontends/${zone}/src/routes`, '-name', '+server.ts'],
		{
			cwd: FRONTEND_ROOT,
			encoding: 'utf8',
		},
	);
	return (
		out
			.split('\n')
			.filter(Boolean)
			.map((f) =>
				f.replace(`components/frontends/${zone}/src/routes`, '').replace('/+server.ts', ''),
			)
			.filter((r) => r.startsWith('/api/'))
			// The catch-all is the zone's default upstream by definition; it has no literal to grep for.
			.filter((r) => !r.endsWith('[...path]'))
	);
}

describe.each(zoneDirs())('%s: every BFF route has a caller', (zone) => {
	const routes = bffRoutes(zone);
	if (routes.length === 0) {
		it('has no non-catch-all BFF routes', () => expect(routes).toEqual([]));
		return;
	}
	it.each(routes)('%s is called by something', (route) => {
		// A dynamic segment is built at the call site, so match the static prefix before it.
		const literal = route.split('/[')[0] ?? route;
		const callers = grep(literal)
			.split('\n')
			.filter(Boolean)
			.filter((f) => !f.includes(`/routes${route.split('/[')[0]}`));
		expect(
			callers.length,
			`${zone}${route} is proxied to a backend but nothing calls it`,
		).toBeGreaterThan(0);
	});
});

describe('the media zone does not proxy the annotation write surface', () => {
	// The narrow, deliberate exception: media's workflow writes tags and submits batch jobs. Anything
	// broader than that belongs to the annotator zone.
	const ALLOWED = ['/api/annotations/tags'];
	it('exposes no /api/annotations route beyond the allowed ones', () => {
		const routes = bffRoutes('media').filter((r) => r.startsWith('/api/annotations'));
		expect(routes.sort()).toEqual(ALLOWED);
	});
	it('exposes no /api/assist route at all', () => {
		expect(bffRoutes('media').filter((r) => r.startsWith('/api/assist'))).toEqual([]);
	});
});

describe('no zone declares an upstream it never routes to', () => {
	it.each(zoneDirs())('%s', (zone) => {
		const server = `components/frontends/${zone}/server.ts`;
		let src: string;
		try {
			src = readFileSync(`${FRONTEND_ROOT}/${server}`, 'utf8');
		} catch {
			return; // not every zone has a thin local server
		}
		for (const m of src.matchAll(/^const ([A-Z_]+) = /gm)) {
			const name = m[1]!;
			const uses = [...src.matchAll(new RegExp(`\\b${name}\\b`, 'g'))].length;
			expect(uses, `${server}: ${name} is declared but never used as an upstream`).toBeGreaterThan(
				1,
			);
		}
	});
});
