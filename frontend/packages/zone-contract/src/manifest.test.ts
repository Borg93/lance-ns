import { describe, expect, it } from 'vitest';
import {
	chartApps,
	devScript,
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
