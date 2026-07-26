import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	chartApps,
	devScript,
	FRONTEND_ROOT,
	hasLintableFiles,
	REPO_ROOT,
	packageName,
	routingConfig,
	svelteBase,
	vitePort,
	zoneDirs,
} from './manifest';

const zones = zoneDirs();
const config = routingConfig();
const apps = chartApps();

/** The catch-all zone: owns '/', so no base path and no routing entry of its own. */
const CATCH_ALL = 'home';

/** Every workspace package, as a frontend-root-relative directory. */
function workspacePackages(): string[] {
	return ['packages', 'components/frontends'].flatMap((dir) =>
		readdirSync(resolve(FRONTEND_ROOT, dir), { withFileTypes: true })
			.filter(
				(e) => e.isDirectory() && existsSync(resolve(FRONTEND_ROOT, dir, e.name, 'package.json')),
			)
			.map((e) => `${dir}/${e.name}`),
	);
}

describe('every zone directory is a declared application', () => {
	it('has a zone to test', () => {
		expect(zones.length).toBeGreaterThan(1);
	});

	it.each(zones)('%s is in microfrontends.json', (zone) => {
		// media and annotator were real, Ingress-routed zones that this file did not mention at all, so
		// the dev composition proxy had no route to them.
		expect(Object.keys(config.applications)).toContain(zone);
	});

	it.each(zones)('%s is in the chart frontend.apps list', (zone) => {
		expect(apps.map((a) => a.name)).toContain(zone);
	});

	it('declares no application that has no zone directory', () => {
		expect(Object.keys(config.applications).sort()).toEqual(zones);
	});

	it('lists no chart app that has no zone directory', () => {
		expect(apps.map((a) => a.name).sort()).toEqual(zones);
	});

	it.each(zones)('%s is the package name too, so turbo can route to it', (zone) => {
		// Turborepo resolves microfrontends.json keys against workspace PACKAGE names. media and
		// annotator kept the standalone repo's @lance-media/* scope, so turbo could not match them to
		// their routing entries and the local proxy silently skipped both zones.
		expect(packageName(zone)).toBe(zone);
	});
});

describe('base path, routing config and Ingress route agree', () => {
	it.each(zones.filter((z) => z !== CATCH_ALL))('%s owns /<zone> everywhere', (zone) => {
		// The base path IS the asset prefix (micro-frontends: independently deployed apps serve assets
		// from one origin, so each needs a unique prefix). If it drifts from the path the proxy and the
		// Ingress route, the zone's own chunks 404.
		expect(svelteBase(zone)).toBe(`/${zone}`);
		expect(config.applications[zone]?.routing?.[0]?.paths).toEqual([`/${zone}`, `/${zone}/:path*`]);
		expect(apps.find((a) => a.name === zone)?.path).toBe(`/${zone}`);
	});

	it('the catch-all zone has no base path and owns "/" in the chart', () => {
		expect(svelteBase(CATCH_ALL)).toBe('');
		expect(config.applications[CATCH_ALL]?.routing).toBeUndefined();
		expect(apps.find((a) => a.name === CATCH_ALL)?.catchAll).toBe(true);
	});
});

describe('dev ports are unique, strict, and single-sourced', () => {
	it('no two zones claim the same port', () => {
		// annotator and models both claimed 5176; models bound it with strictPort and won the race, so
		// the annotator drifted to another port and every /annotator link landed on models.
		const ports = zones.map((z) => config.applications[z]?.development?.local?.port);
		expect(new Set(ports).size).toBe(ports.length);
		expect(ports.every((p) => typeof p === 'number')).toBe(true);
	});

	it.each(zones)('%s binds the port the routing config declares, strictly', (zone) => {
		const declared = config.applications[zone]?.development?.local?.port;
		expect(vitePort(zone)).toEqual({ port: declared, strict: true });
	});

	it.each(zones)('%s does not ALSO set a port in its dev script', (zone) => {
		// Two places to change a port is how they drift; vite.config.ts is the single source.
		expect(devScript(zone)).not.toMatch(/--port/);
	});
});

describe('there is exactly one config per tool, at the workspace root', () => {
	// media and annotator arrived from a standalone repo that already used the oxc toolchain, and
	// carried their own .oxfmtrc.json / .oxlintrc.json in. Both tools resolve the NEAREST config
	// upward, so those files silently overrode the root config for that zone the moment oxlint and
	// oxfmt were switched on — media got 80-column double-quoted output and a different plugin set,
	// and nothing reported it. A per-package config must be a deliberate act, not a leftover.
	// The prettier / eslint entries stay in this list AFTER both tools were removed: the failure mode
	// is a file reappearing (a generator, a copied package, an editor plugin) and configuring a tool
	// nothing runs, which reads as coverage that does not exist.
	it.each([
		'.oxlintrc.json',
		'.oxfmtrc.json',
		'.prettierrc',
		'.prettierrc.json',
		'eslint.config.js',
	])('%s exists only at the frontend root', (name) => {
		const strays: string[] = [];
		for (const dir of ['packages', 'components/frontends']) {
			for (const pkg of readdirSync(resolve(FRONTEND_ROOT, dir), { withFileTypes: true })) {
				if (!pkg.isDirectory()) continue;
				const found = readdirSync(resolve(FRONTEND_ROOT, dir, pkg.name));
				if (found.includes(name)) strays.push(`${dir}/${pkg.name}/${name}`);
			}
		}
		expect(strays).toEqual([]);
	});

	// Two tools, two commands, everywhere. rsvelte-fmt formats `.svelte` in process and delegates every
	// other extension to oxfmt, and oxlint hosts the Svelte rules through @rsvelte/oxlint-plugin — so a
	// package that still spawns eslint or prettier is running a toolchain that is no longer installed,
	// and `--no-error-on-unmatched-pattern` would make that look like a pass.
	// `--no-error-on-unmatched-pattern` is allowed for EXACTLY the packages that have no lintable file
	// (a config-only package like @repo/config ships two JSON files; plain `oxlint .` exits 1 there, so
	// without this the package must drop the script — the omission the next assertion forbids). It is
	// FORBIDDEN for every package that does have source, which is the masking case the comment above
	// warns about: the filesystem decides which command a package must declare, so the flag can never
	// hide a zone whose paths stopped matching.
	const lintFor = (pkg: string) =>
		hasLintableFiles(resolve(FRONTEND_ROOT, pkg))
			? 'oxlint .'
			: 'oxlint --no-error-on-unmatched-pattern .';
	const EXPECTED: Record<string, string> = {
		fmt: 'rsvelte-fmt .',
		'fmt:check': 'rsvelte-fmt --check .',
	};
	it.each(workspacePackages())('%s runs the one lint and format command', (pkg) => {
		const { scripts = {} } = JSON.parse(
			readFileSync(resolve(FRONTEND_ROOT, pkg, 'package.json'), 'utf8'),
		) as { scripts?: Record<string, string> };
		// REQUIRED, not just "correct if present". Skipping an absent task made the gate vacuous in
		// the direction that actually happens: a package does not drift to a WRONG command, it ships
		// with NO lint/fmt scripts and turbo then has nothing to run for it — silently outside the
		// toolchain while every gate stays green. @repo/config was exactly that (found 2026-07-25:
		// two JSON files, no scripts, never format-checked). A package with genuinely nothing to
		// check still declares them; oxlint/rsvelte-fmt over zero matching files is free.
		for (const [task, expected] of Object.entries({ ...EXPECTED, lint: lintFor(pkg) })) {
			expect(scripts[task], `${pkg} is missing the shared ${task} script`).toBe(expected);
		}
		for (const [task, script] of Object.entries(scripts)) {
			expect(script, `${pkg} ${task} still invokes a removed tool`).not.toMatch(
				/\b(eslint|prettier)\b/,
			);
		}
	});
});

/** A zone's e2e helper servers (mock backends) — the other place a port literal hides. */
function e2eServers(zone: string): string[] {
	const dir = resolve(FRONTEND_ROOT, `components/frontends/${zone}/e2e`);
	if (!existsSync(dir)) return [];
	return readdirSync(dir, { recursive: true, encoding: 'utf8' })
		.filter((f) => f.endsWith('.ts') && !f.endsWith('.spec.ts'))
		.map((f) => `e2e/${f}`);
}

describe('no two zones bind the same port, in dev OR in e2e', () => {
	// The dev ports are checked above against microfrontends.json. The E2E ports are not in any
	// manifest, and playwright runs with `reuseExistingServer` locally — so a duplicate does not fail
	// loudly with EADDRINUSE, it silently ADOPTS whatever is already listening. The lakehouse admin
	// suite's mock catalog sat on 5297, which is the media zone's e2e server; a parallel local run
	// pointed the admin tests at a real dev server and called it the mock.
	const declared = zones.flatMap((zone) =>
		['vite.config.ts', 'playwright.config.ts', ...e2eServers(zone)]
			.map((f) => resolve(FRONTEND_ROOT, `components/frontends/${zone}`, f))
			.filter((p) => existsSync(p))
			.flatMap((p) => {
				const src = readFileSync(p, 'utf8');
				// Only a port a zone BINDS: `port: 5294` (vite `server.port`, playwright `webServer.port`)
				// and `const MOCK_CATALOG_PORT = 5292`. Deliberately not any 4-digit literal — a proxy
				// TARGET (`http://127.0.0.1:5177`, `http://localhost:8001`) is a zone pointing at something
				// else, and two zones proxying the same backend is correct, not a collision.
				const found = [...src.matchAll(/(?:\bport:\s*|PORT\s*=\s*)(\d{4})/g)];
				return found.map((m) => ({ zone, port: Number(m[1]) }));
			}),
	);

	it('finds the ports to compare', () => {
		expect(declared.length).toBeGreaterThan(zones.length);
	});

	it.each([...new Set(declared.map((d) => d.port))])(
		'%d is claimed by exactly one zone',
		(port) => {
			const claimants = [...new Set(declared.filter((d) => d.port === port).map((d) => d.zone))];
			expect(claimants).toHaveLength(1);
		},
	);
});

describe('the budget gate is ordered after the builds it weighs', () => {
	// budget.test.ts measures each zone's .svelte-kit/output/client. turbo's `test -> build` edge only
	// orders a package against ITSELF, and no zone depends on @repo/zone-contract (it is a gate, not a
	// runtime dep), so `turbo run test build` ran the two concurrently and the budget was measured off a
	// half-written directory. The explicit per-zone edge fixes the order; this keeps it from drifting.
	// turbo.json is JSONC — drop whole-line // comments before parsing (never a partial line, so a
	// `//` inside a string value can't be clipped).
	const turbo = JSON.parse(
		readFileSync(resolve(FRONTEND_ROOT, 'turbo.json'), 'utf8')
			.split('\n')
			.filter((l) => !l.trimStart().startsWith('//'))
			.join('\n'),
	) as { tasks: Record<string, { dependsOn?: string[] }> };
	const deps = turbo.tasks['@repo/zone-contract#test']?.dependsOn;

	it('depends on every zone build, and only those', () => {
		expect(deps?.slice().sort()).toEqual(zones.map((z) => `${z}#build`).sort());
	});
});

describe('the Makefile builds and loads exactly the zones that exist', () => {
	// `ZONES` drives `make frontend-images` (docker build --build-arg APP=$z), `make frontend-load` and
	// `make load` (kind load docker-image lance-$z:dev). It still listed the SEVEN pre-merge zones, so
	// the first command anyone would run in a real cluster — `make images`, hence `make up` — died on
	// `bun run --cwd components/frontends/data build` and never reached lakehouse. Nothing type-checks a
	// Makefile and no CI leg builds the images, so this is the only thing that can catch it.
	const makefile = readFileSync(resolve(REPO_ROOT, 'Makefile'), 'utf8');
	const declared = (/^ZONES\s*:?=\s*(.+)$/m.exec(makefile)?.[1] ?? '').trim().split(/\s+/);

	it('declares a ZONES list', () => {
		expect(declared.filter(Boolean).length).toBeGreaterThan(0);
	});

	it('names every zone directory, and nothing else', () => {
		expect([...declared].sort()).toEqual([...zones].sort());
	});
});

describe('the zone image can actually install the workspace', () => {
	// `bun install --frozen-lockfile` inside .docker/frontend.dockerfile fails with "Workspace not
	// found" if a member of `workspaces` was never COPYed in — and nothing else catches it, because no
	// CI leg builds the images. It already happened: `eslint-rules` was a workspace member the
	// dockerfile never copied, so every zone image build had been broken since it was added, and it was
	// only fixed as a side effect of deleting ESLint.
	const dockerfile = readFileSync(resolve(REPO_ROOT, '.docker/frontend.dockerfile'), 'utf8');
	const copied = [...dockerfile.matchAll(/^COPY\s+(.+)$/gm)].flatMap((m) =>
		m[1]!.split(/\s+/).filter((t) => t.startsWith('frontend/')),
	);
	const { workspaces = [] } = JSON.parse(
		readFileSync(resolve(FRONTEND_ROOT, 'package.json'), 'utf8'),
	) as { workspaces?: string[] };

	it('finds the COPY lines to check', () => {
		expect(copied.length).toBeGreaterThan(2);
		expect(workspaces.length).toBeGreaterThan(0);
	});

	it.each(workspaces)('the builder copies the %s workspace', (glob) => {
		// `packages/*` is covered by `COPY frontend/packages`, `eslint-rules` would need its own line.
		const root = `frontend/${glob.replace(/\/\*+$/, '')}`;
		expect(copied, `.docker/frontend.dockerfile never COPYs ${root}`).toContain(root);
	});
});

describe('nothing outside the frontend still points at a moved path', () => {
	// The renames kept breaking things OUTSIDE the source tree: .docker/frontend.dockerfile pre-built
	// `packages/rask-ui`, chart/templates named `@rask/api`, and scripts/verify_cross_zone_oidc.*
	// navigated to `/data` and `/models/pipeline`. None of it is type-checked, none of it is linted,
	// and all of it is on the deploy path — the dockerfile one would have failed every zone image
	// build. A rename is not done until this passes.
	const DEAD = ['@rask/', '@lance/', 'packages/rask-ui', 'components/frontends/data'];
	const SEARCHED = [
		'Makefile',
		'.docker/frontend.dockerfile',
		'chart/templates/frontends.yaml',
		'chart/templates/ingress.yaml',
		'chart/values.yaml',
		'scripts/verify_cross_zone_oidc.sh',
		'scripts/verify_cross_zone_oidc.mjs',
		'.github/workflows/ci.yml',
		'.dagger/frontend.go',
	];

	it.each(SEARCHED)('%s names no retired package or zone', (rel) => {
		const path = resolve(REPO_ROOT, rel);
		if (!existsSync(path)) return; // the file moving is a separate, visible change
		const src = readFileSync(path, 'utf8');
		expect(DEAD.filter((d) => src.includes(d))).toEqual([]);
	});

	// The list above holds PACKAGE and DIRECTORY names, so a retired URL path walked straight through it —
	// including in the very file the comment names. `verify_cross_zone_oidc.sh` polled
	// `http://localhost:$ORIGIN_PORT/data` as its readiness probe; the merge made that a 404, so the probe
	// never matched, the loop fail()ed after 30 tries, and the ONE script that proves cross-zone OIDC end
	// to end could not start. That is why five dead `/data` links reached main with every gate green: the
	// artifact that would have walked into them was itself broken by the same rename.
	//
	// Only lines carrying a URL are checked, and only the pre-merge zone roots. `/data` as a filesystem
	// path or a values key is none of this gate's business, and a false positive here is how a gate gets
	// deleted rather than fixed.
	const DEAD_URL_PATHS = ['data', 'lineage', 'models', 'admin'];
	it.each(SEARCHED)('%s drives no retired ORIGIN path', (rel) => {
		const path = resolve(REPO_ROOT, rel);
		if (!existsSync(path)) return;
		const offences: string[] = [];
		readFileSync(path, 'utf8')
			.split('\n')
			.forEach((line, i) => {
				if (!line.includes('http')) return;
				if (line.trimStart().startsWith('#')) return; // prose, not a request
				for (const dead of DEAD_URL_PATHS) {
					// A URL path segment right after the authority: `…:$PORT/data`, `…example.com/lineage`.
					if (new RegExp(`https?://[^/\\s"']+/${dead}(?=["'/?\\s]|$)`).test(line)) {
						offences.push(
							`${rel}:${i + 1} requests /${dead} — an area of /lakehouse since the merge`,
						);
					}
				}
			});
		expect(offences).toEqual([]);
	});
});
