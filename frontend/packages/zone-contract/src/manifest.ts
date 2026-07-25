// The zone manifest, read back out of the four files that declare it. Pure parsing — the assertions
// live in manifest.test.ts. Deliberately regex/JSON based rather than importing the configs: the point
// is to read what is WRITTEN in each file, so a value that only agrees because one file imports the
// other still counts as a disagreement.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** frontend/ — this package lives at frontend/packages/zone-contract/src. */
export const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
/** The repo root, one level above frontend/ — where chart/ lives. */
export const REPO_ROOT = resolve(FRONTEND_ROOT, '..');

const read = (path: string) => readFileSync(resolve(FRONTEND_ROOT, path), 'utf8');

export interface RoutingConfigApp {
	development?: { local?: { port?: number } };
	routing?: { paths: string[] }[];
}

export interface RoutingConfig {
	applications: Record<string, RoutingConfigApp>;
}

/** `components/frontends/home/microfrontends.json` — the default app ships the routing config. */
export function routingConfig(): RoutingConfig {
	return JSON.parse(read('components/frontends/home/microfrontends.json')) as RoutingConfig;
}

/** The zone directories that actually exist under components/frontends — the ground truth every other
 *  declaration is checked against. */
export function zoneDirs(): string[] {
	return readdirSync(resolve(FRONTEND_ROOT, 'components/frontends'), { withFileTypes: true })
		.filter((e) => e.isDirectory())
		.map((e) => e.name)
		.sort();
}

/** The `paths.base` a zone serves under, from its svelte.config.js. `''` for the catch-all zone. */
export function svelteBase(zone: string): string {
	const src = read(`components/frontends/${zone}/svelte.config.js`);
	return /paths:\s*\{[^}]*base:\s*'([^']*)'/.exec(src)?.[1] ?? '';
}

/** The dev port a zone's vite.config.ts binds, and whether it binds it strictly. */
export function vitePort(zone: string): { port: number | null; strict: boolean } {
	const src = read(`components/frontends/${zone}/vite.config.ts`);
	const port = /^\s*port:\s*(\d+)/m.exec(src)?.[1];
	return { port: port ? Number(port) : null, strict: /strictPort:\s*true/.test(src) };
}

/** A zone's package name. Turborepo resolves `microfrontends.json` application keys against WORKSPACE
 *  PACKAGE names, so a zone whose package is scoped differently than its key is silently unroutable —
 *  `turbo boundaries` warns, nothing fails. */
export function packageName(zone: string): string {
	return JSON.parse(read(`components/frontends/${zone}/package.json`)).name as string;
}

/** A zone's `dev` script, so we can assert the port is not ALSO declared there (two sources of truth). */
export function devScript(zone: string): string {
	return JSON.parse(read(`components/frontends/${zone}/package.json`)).scripts?.dev ?? '';
}

export interface ChartApp {
	name: string;
	path: string | null;
	catchAll: boolean;
}

/** `chart/values.yaml` → `frontend.apps`. Parsed from the flow-mapping list entries so this stays a
 *  dependency-free read (no YAML parser in the frontend workspace). */
export function chartApps(): ChartApp[] {
	const yaml = readFileSync(resolve(REPO_ROOT, 'chart/values.yaml'), 'utf8');
	const block = /^\s{2}apps:\s*$/m.exec(yaml);
	if (!block) return [];
	const rest = yaml.slice(block.index + block[0].length);
	const end = /^\s{0,2}\w/m.exec(rest);
	const body = end ? rest.slice(0, end.index) : rest;
	return [...body.matchAll(/^\s*-\s*\{([^}]*)\}/gm)].map((m) => {
		const entry = m[1] ?? '';
		return {
			name: /name:\s*([\w-]+)/.exec(entry)?.[1] ?? '',
			path: /path:\s*(\/[\w-]*)/.exec(entry)?.[1] ?? null,
			catchAll: /catchAll:\s*true/.test(entry),
		};
	});
}
