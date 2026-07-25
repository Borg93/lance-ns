import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FRONTEND_ROOT, zoneDirs } from './manifest';
import budget from './budget.json' with { type: 'json' };

/**
 * The composed-page bundle budget.
 *
 * Micro-frontends make bundle regressions invisible: each zone looks fine on its own, nobody measures
 * the estate, and the cost only shows up as a slow cross-zone hop. That gets worse now that the zones
 * ship on independent tags — no single release looks at all four. So the ceiling is committed, and
 * raising it is an edit someone has to justify rather than a number that drifts.
 *
 * Measured over every emitted .js/.css, gzipped together: that is what the browser pays to enter a
 * zone. It is deliberately NOT per-route — the point is the cost of crossing a zone boundary.
 */
const CLIENT = (zone: string) => `components/frontends/${zone}/.svelte-kit/output/client`;

function gzippedKB(zone: string): number | null {
	const dir = resolve(FRONTEND_ROOT, CLIENT(zone));
	if (!existsSync(dir)) return null;
	const files = execFileSync(
		'find',
		[dir, '-type', 'f', '(', '-name', '*.js', '-o', '-name', '*.css', ')'],
		{ encoding: 'utf8' },
	)
		.split('\n')
		.filter(Boolean);
	if (files.length === 0) return null;
	const combined = Buffer.concat(files.map((f) => readFileSync(f)));
	return Math.round(gzipSync(combined, { level: 9 }).length / 1024);
}

const zones = zoneDirs();

describe('every zone has a declared budget', () => {
	it.each(zones)('%s', (zone) => {
		expect(Object.keys(budget.zones), `add ${zone} to budget.json`).toContain(zone);
	});

	it('declares no budget for a zone that no longer exists', () => {
		expect(Object.keys(budget.zones).sort()).toEqual([...zones].sort());
	});
});

describe('client bundles stay inside their budget', () => {
	it.each(zones)('%s', (zone) => {
		const actual = gzippedKB(zone);
		if (actual === null) {
			// `turbo run test` does not depend on `build`, so a clean checkout has nothing to weigh. The
			// gate runs wherever a build exists (CI runs build before test:e2e, and locally after any
			// `bun run build`); it must not fail for being unable to measure.
			return;
		}
		const limit = (budget.zones as Record<string, { gzipKB: number }>)[zone]!.gzipKB;
		expect(
			actual,
			`${zone} client bundle is ${actual} KB gzipped, over its ${limit} KB budget. ` +
				`Cut it, or raise the number in budget.json WITH the reason in the commit message.`,
		).toBeLessThanOrEqual(limit);
	});
});

describe('the annotator split still pays for itself', () => {
	it('annotator is materially heavier than media, which is why it is its own zone', () => {
		// If these ever converge, the bundle-isolation argument for a separate annotator zone is gone
		// and it should become an area of media — the same test the other four zones failed.
		const a = budget.zones.annotator.gzipKB;
		const m = budget.zones.media.gzipKB;
		expect(a).toBeGreaterThan(m * 2);
	});
});
