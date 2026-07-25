import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	chartApps,
	devScript,
	FRONTEND_ROOT,
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
});

describe('nothing outside the frontend still points at a moved path', () => {
	// The renames kept breaking things OUTSIDE the source tree: .docker/frontend.dockerfile pre-built
	// `packages/rask-ui`, chart/templates named `@rask/api`, and scripts/verify_cross_zone_oidc.*
	// navigated to `/data` and `/models/pipeline`. None of it is type-checked, none of it is linted,
	// and all of it is on the deploy path — the dockerfile one would have failed every zone image
	// build. A rename is not done until this passes.
	const DEAD = ['@rask/', '@lance/', 'packages/rask-ui', 'components/frontends/data'];
	const SEARCHED = [
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
});
