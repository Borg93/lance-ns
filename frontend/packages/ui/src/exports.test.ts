// The lib's public surface — a rename/removal fails HERE before any app import breaks.
// (fs-based: bun test has no .svelte loader; svelte-check type-checks the real imports.)
import { expect, test } from 'bun:test';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const src = import.meta.dir;

test('every exported component file exists', () => {
	const index = readFileSync(join(src, 'index.ts'), 'utf8');
	const files = [...new Set([...index.matchAll(/from '\.\/(\w+\.svelte)'/g)].map((m) => m[1]))];
	expect(files.sort()).toEqual(['Chip.svelte', 'SearchBar.svelte']);
	for (const f of files) expect(existsSync(join(src, f))).toBe(true);
});

test('components are transport-agnostic (no fetch, no app imports)', () => {
	for (const f of ['Chip.svelte', 'SearchBar.svelte']) {
		const body = readFileSync(join(src, f), 'utf8');
		expect(body.includes("from '$lib")).toBe(false); // never reach into an app
		expect(/\bfetch\(/.test(body)).toBe(false); // callers own the API client (rask convention)
	}
});
