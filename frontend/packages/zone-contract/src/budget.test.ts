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
 * MEASURED IN TWO HALVES, and that distinction is the whole point of this gate.
 *
 * The first version gzipped every emitted .js/.css together and called the result "what the browser
 * pays to enter a zone". For three zones that was near enough. For the annotator it was false by an
 * order of magnitude: 3809 of its 4179 KB was ONE chunk — the vendored OpenCV wasm — reached only
 * through a dynamic `import()` inside the magnetic tool, so a session that never picks that tool never
 * downloads a byte of it. The consequences were worse than the wrong number:
 *
 *   - The annotator read as 4179/4800 KB — 87% of budget "used" — while its real entry cost was 324 KB.
 *     A change that doubled the entry graph would have passed the gate without a murmur, because 400 KB
 *     is noise next to a 3.8 MB constant. The gate could not see the regression it exists to catch.
 *   - It made the estate's shape unreadable. On entry cost the annotator is the SECOND-LIGHTEST zone
 *     (324 KB, against media's 927) — the opposite of what the old number said, and the opposite of
 *     what budget.json's own note claimed.
 *
 * So: `staticGzipKB` is the closure of STATIC imports from every entry Vite emitted (SvelteKit marks
 * entry/start, entry/app and every route node as entries), plus their CSS — code the zone can load
 * without a user action, i.e. what crossing the boundary actually costs. `deferredGzipKB` is
 * everything else: real bytes, but ones the user opts into. Both are ceilinged, because an unbounded
 * lazy payload is still a problem — just a different problem, on a different budget.
 *
 * Read from Vite's own manifest rather than reconstructed by parsing import statements: the manifest
 * distinguishes `imports` from `dynamicImports` at the source of truth, and a regex over minified
 * output cannot tell `import"./x.js"` from `import("./x.js")` reliably.
 */
const CLIENT = (zone: string) => `components/frontends/${zone}/.svelte-kit/output/client`;

interface ViteChunk {
	file: string;
	isEntry?: boolean;
	imports?: string[];
	dynamicImports?: string[];
	css?: string[];
}

interface Weighed {
	staticKB: number;
	deferredKB: number;
	/** Emitted files reachable only through a dynamic import — what the deferred number is made of. */
	deferredFiles: string[];
	staticFiles: string[];
}

/** Gzip a set of files TOGETHER — one stream, the way a browser would receive them over one connection. */
function gzipKB(dir: string, files: string[]): number {
	if (files.length === 0) return 0;
	const combined = Buffer.concat(files.map((f) => readFileSync(resolve(dir, f))));
	return Math.round(gzipSync(combined, { level: 9 }).length / 1024);
}

/** Split a zone's client output into the static-import closure and everything only reachable lazily.
 *  `null` when there is nothing to weigh (no build in this checkout). */
function weigh(zone: string): Weighed | null {
	const dir = resolve(FRONTEND_ROOT, CLIENT(zone));
	const manifestPath = resolve(dir, '.vite/manifest.json');
	if (!existsSync(manifestPath)) return null;
	const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Record<string, ViteChunk>;
	const chunks = Object.values(manifest);
	const byFile = new Map(chunks.map((c) => [c.file, c]));
	/** A chunk's `imports` name manifest KEYS, not emitted files — resolve both spellings. */
	const emitted = (ref: string) => manifest[ref]?.file ?? ref;

	const reached = new Set<string>();
	const css = new Set<string>();
	const stack = chunks.filter((c) => c.isEntry).map((c) => c.file);
	while (stack.length > 0) {
		const file = stack.pop()!;
		if (reached.has(file)) continue;
		reached.add(file);
		const chunk = byFile.get(file);
		for (const sheet of chunk?.css ?? []) css.add(sheet);
		// STATIC edges only. Following dynamicImports here would rebuild the very number this gate replaced.
		for (const ref of chunk?.imports ?? []) {
			const target = emitted(ref);
			if (!reached.has(target)) stack.push(target);
		}
	}

	const staticFiles = [...new Set([...reached, ...css])].sort();
	const all = new Set<string>();
	for (const chunk of chunks) {
		all.add(chunk.file);
		for (const sheet of chunk.css ?? []) all.add(sheet);
	}
	const deferredFiles = [...all].filter((f) => !staticFiles.includes(f)).sort();

	return {
		staticKB: gzipKB(dir, staticFiles),
		deferredKB: gzipKB(dir, deferredFiles),
		deferredFiles,
		staticFiles,
	};
}

const zones = zoneDirs();
type Zone = { staticGzipKB: number; deferredGzipKB: number };
const limits = budget.zones as Record<string, Zone>;

describe('every zone has a declared budget', () => {
	it.each(zones)('%s', (zone) => {
		expect(Object.keys(limits), `add ${zone} to budget.json`).toContain(zone);
	});

	it('declares no budget for a zone that no longer exists', () => {
		expect(Object.keys(limits).sort()).toEqual([...zones].sort());
	});
});

describe('the code a zone loads on entry stays inside its budget', () => {
	it.each(zones)('%s', (zone) => {
		const weighed = weigh(zone);
		if (weighed === null) {
			// `turbo run test` does not depend on `build`, so a clean checkout has nothing to weigh. The
			// gate runs wherever a build exists (CI runs build before test:e2e, and locally after any
			// `bun run build`); it must not fail for being unable to measure.
			return;
		}
		const limit = limits[zone]!.staticGzipKB;
		expect(
			weighed.staticKB,
			`${zone} loads ${weighed.staticKB} KB gzipped on entry, over its ${limit} KB budget. ` +
				`Cut it, defer it behind a dynamic import, or raise the number in budget.json WITH the ` +
				`reason in the commit message.`,
		).toBeLessThanOrEqual(limit);
	});
});

describe('lazily-loaded payloads stay inside their own budget', () => {
	it.each(zones)('%s', (zone) => {
		const weighed = weigh(zone);
		if (weighed === null) return;
		const limit = limits[zone]!.deferredGzipKB;
		expect(
			weighed.deferredKB,
			`${zone} ships ${weighed.deferredKB} KB gzipped behind dynamic imports, over its ${limit} KB ` +
				`budget. Deferred is not free — someone waits for it the first time they use the feature.`,
		).toBeLessThanOrEqual(limit);
	});
});

describe('the OpenCV wasm stays lazy', () => {
	// The specific invariant behind the annotator's shape: a static import of @techstark/opencv-js
	// anywhere in the annotator would move ~3.8 MB gzipped onto the entry path. The static budget above
	// would catch the size, but this names the cause, which is what the next person needs.
	it('is reachable only through a dynamic import', () => {
		const weighed = weigh('annotator');
		if (weighed === null) return;
		const dir = resolve(FRONTEND_ROOT, CLIENT('annotator'));
		const carriesOpenCv = (f: string) =>
			f.endsWith('.js') && readFileSync(resolve(dir, f), 'utf8').includes('opencv');
		expect(
			weighed.staticFiles.filter(carriesOpenCv),
			'OpenCV reached the annotator entry graph — it must stay behind the magnetic tool import',
		).toEqual([]);
		expect(
			weighed.deferredFiles.some(carriesOpenCv),
			'OpenCV is not in the deferred set either — has the magnetic tool lost its wasm?',
		).toBe(true);
	});
});

describe('the annotator split still pays for itself', () => {
	it('the annotator costs LESS to enter than media, because its weight is deferred', () => {
		// The original form of this test asserted the opposite ("annotator is materially heavier than
		// media, which is why it is its own zone") against the DECLARED numbers. Measured, the premise was
		// false: the annotator's entry cost is a third of media's. The split still pays — but for the
		// other reason. What a searcher is spared is the deferred 3.8 MB, not the entry graph, and that
		// only stays true while the heavy part stays lazy. So this now guards the real invariant, and the
		// OpenCV test above guards its cause.
		const a = weigh('annotator');
		const m = weigh('media');
		if (a === null || m === null) return;
		expect(a.staticKB).toBeLessThan(m.staticKB);
		expect(
			a.deferredKB,
			'the annotator no longer defers a large payload — is the separate zone still buying anything?',
		).toBeGreaterThan(m.deferredKB);
	});
});
