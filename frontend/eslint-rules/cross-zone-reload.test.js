import { describe, expect, it } from 'vitest';
import { isCrossZonePath } from './cross-zone-reload.js';

// Cross-zone hrefs are single-segment, domain-relative (`/data/tables`, `/lineage`).
// The guard predicate must match the current scheme or it silently protects nothing.
describe('isCrossZonePath', () => {
	it('matches a nested cross-zone path', () => {
		expect(isCrossZonePath('/data/tables')).toBe(true);
		expect(isCrossZonePath('/admin/dlq')).toBe(true);
	});

	it('matches a bare domain landing', () => {
		expect(isCrossZonePath('/lineage')).toBe(true);
		expect(isCrossZonePath('/models')).toBe(true);
	});

	it('ignores same-zone / non-zone and opaque-expression hrefs', () => {
		expect(isCrossZonePath('/')).toBe(false);
		expect(isCrossZonePath('/api/runs')).toBe(false);
		// A leading `{base}` expression renders as the opaque placeholder — never a zone.
		expect(isCrossZonePath('￿/tables')).toBe(false);
	});

	it('does NOT match a two-segment /default/<domain> form', () => {
		expect(isCrossZonePath('/default/data')).toBe(false);
	});
});
