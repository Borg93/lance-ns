import { describe, expect, it } from 'vitest';
import { isCrossZonePath } from './cross-zone-reload.js';

// Cross-zone hrefs are single-segment, domain-relative (`/lakehouse/data/tables`, `/media`).
// The guard predicate must match the current scheme or it silently protects nothing.
describe('isCrossZonePath', () => {
	it('matches a nested cross-zone path', () => {
		expect(isCrossZonePath('/lakehouse/data/tables')).toBe(true);
		expect(isCrossZonePath('/media/atlas')).toBe(true);
	});

	it('matches a bare zone landing', () => {
		expect(isCrossZonePath('/lakehouse')).toBe(true);
		expect(isCrossZonePath('/annotator')).toBe(true);
	});

	it('does NOT match a hop BETWEEN areas of the merged lakehouse zone', () => {
		// data / lineage / models / admin used to be four zones, so a link between them had to
		// hard-navigate. They are one zone now: these are same-zone soft navs, and flagging them would
		// force a full document reload where the router can handle it.
		expect(isCrossZonePath('/data/tables')).toBe(false);
		expect(isCrossZonePath('/lineage')).toBe(false);
		expect(isCrossZonePath('/models/experiments')).toBe(false);
		expect(isCrossZonePath('/admin/dlq')).toBe(false);
	});

	it('ignores same-zone / non-zone and opaque-expression hrefs', () => {
		expect(isCrossZonePath('/')).toBe(false);
		expect(isCrossZonePath('/api/runs')).toBe(false);
		// A leading `{base}` expression renders as the opaque placeholder — never a zone.
		expect(isCrossZonePath('￿/tables')).toBe(false);
	});

	it('does NOT match a two-segment /default/<zone> form', () => {
		expect(isCrossZonePath('/default/lakehouse')).toBe(false);
	});
});
