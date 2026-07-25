/**
 * The local composition edge: one origin, all zones — the dev-time stand-in for the cluster Ingress.
 *
 * Without it, `turbo run dev` gives you seven separate origins on seven ports, and every cross-zone
 * behaviour the estate depends on is unreproducible locally: the sealed session cookie is per-origin so
 * a login does not carry, `data-sveltekit-reload` hard navigations go to the wrong host, and the shared
 * `mode-watcher` theme key is scoped to whichever port you happened to be on. Those are exactly the
 * bugs that only show up in the composed page, which is the class the micro-frontends skill says you
 * must have a local harness for.
 *
 * It routes by longest path prefix to the zone that owns it, straight out of
 * `components/frontends/home/microfrontends.json` — the same file the Ingress rules, the base paths and
 * the zone-contract tests are all checked against, so there is no second source of truth. A zone that
 * is not running answers 502 with which zone and which port, instead of a connection reset.
 *
 *   bun run dev:proxy            # or `bun run dev` at the frontend root, which starts both
 *   PROXY_PORT=5200 bun src/proxy.ts
 */
import { routingConfig } from './manifest';

interface Route {
	/** The zone that owns this prefix. */
	zone: string;
	/** '' for the catch-all zone, '/data' etc. otherwise. */
	prefix: string;
	port: number;
}

/** Build the routing table, longest prefix first — the same match order nginx and the Ingress use. */
export function routes(): Route[] {
	const { applications } = routingConfig();
	const table: Route[] = [];
	for (const [zone, app] of Object.entries(applications)) {
		const port = app.development?.local?.port;
		if (typeof port !== 'number') continue;
		const paths = app.routing?.flatMap((r) => r.paths) ?? [];
		// `/data` and `/data/:path*` collapse to the one prefix `/data`; a zone with no routing entry is
		// the catch-all and gets the empty prefix, which sorts last.
		const prefix = paths.length ? (/^(\/[^/:]*)/.exec(paths[0] ?? '')?.[1] ?? '') : '';
		table.push({ zone, prefix, port });
	}
	return table.sort((a, b) => b.prefix.length - a.prefix.length);
}

/** Pick the owning zone for a pathname. Never undefined: the catch-all zone has the '' prefix. */
export function resolve(table: Route[], pathname: string): Route | undefined {
	return table.find(
		(r) => r.prefix === '' || pathname === r.prefix || pathname.startsWith(`${r.prefix}/`),
	);
}

const PORT = Number(process.env.PROXY_PORT ?? 5200);
const table = routes();

Bun.serve({
	port: PORT,
	idleTimeout: 120,
	async fetch(req) {
		const url = new URL(req.url);
		const route = resolve(table, url.pathname);
		if (!route) return new Response(`No zone owns ${url.pathname}`, { status: 404 });

		const target = new URL(url.pathname + url.search, `http://127.0.0.1:${route.port}`);
		try {
			// `redirect: 'manual'` so a zone's own 3xx reaches the browser as-is (the OIDC round-trip and
			// SvelteKit's trailing-slash redirects both depend on it).
			return await fetch(target, {
				method: req.method,
				headers: req.headers,
				body: req.body,
				redirect: 'manual',
				// @ts-expect-error -- Bun-only: stream request bodies rather than buffering uploads.
				duplex: 'half',
			});
		} catch {
			return new Response(
				`Zone "${route.zone}" is not running on port ${route.port}.\n` +
					`Start it with: bun run dev --filter=${route.zone}\n`,
				{ status: 502, headers: { 'content-type': 'text/plain' } },
			);
		}
	},
	// A zone crash must not take the edge down with it.
	error: (err) => new Response(`Proxy error: ${err.message}`, { status: 502 }),
});

console.log(`Zone proxy on http://localhost:${PORT}`);
for (const r of table) console.log(`  ${(r.prefix || '/').padEnd(12)} -> ${r.zone} :${r.port}`);
