// The lib's public surface — a rename/removal fails HERE before any app import breaks.
// (fs-based: bun test has no .svelte loader; svelte-check type-checks the real imports.)
import { expect, test } from "bun:test";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const src = import.meta.dir;

test("every exported component file exists", () => {
	const index = readFileSync(join(src, "index.ts"), "utf8");
	// oxfmt canonicalizes to double quotes; accept either so a formatter change can't blind this test
	const files = [
		...new Set([...index.matchAll(/from ["']\.\/(\w+\.svelte)["']/g)].map((m) => m[1])),
	];
	expect(files.sort()).toEqual([
		"Chip.svelte",
		"SearchBar.svelte",
		"Select.svelte",
		"StatusBoard.svelte",
	]);
	for (const f of files) expect(existsSync(join(src, f))).toBe(true);
});

test("lib sources are transport- and framework-agnostic (no fetch, no $lib, no $app)", () => {
	// EVERY source in the lib (components AND ts modules, recursively), not a hand-kept list — a
	// new file is covered the moment it lands. `$app/*` is banned alongside `$lib/*`: SvelteKit-only
	// aliases don't resolve outside a Kit app (gsap.ts imported `$app/environment` before the
	// extraction and had to cut it — this test keeps that tie from creeping back).
	const sources = readdirSync(src, { recursive: true })
		.map(String)
		.filter((f) => (f.endsWith(".svelte") || f.endsWith(".ts")) && !f.endsWith(".test.ts"));
	expect(sources.length).toBeGreaterThanOrEqual(5); // 3 components + index + attachments/gsap
	for (const f of sources) {
		const body = readFileSync(join(src, f), "utf8");
		expect(/from ["']\$lib/.test(body)).toBe(false); // never reach into an app
		expect(/from ["']\$app/.test(body)).toBe(false); // never depend on SvelteKit aliases
		expect(/\bfetch\(/.test(body)).toBe(false); // callers own the API client (rask convention)
	}
});
