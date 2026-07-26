import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { REPO_ROOT } from './manifest';

/**
 * A live query has to survive TWO idle timeouts, and the estate configures both in the same chart.
 *
 * `query.live` is a server-side generator that yields only when its data changes — the correct
 * discipline, and the one that makes the connection look dead to every hop in front of it. SvelteKit's
 * SSE transport sends no keepalive of its own (kit 2.70.1 `runtime/server/remote.js` has exactly one
 * `controller.enqueue`, the payload), so nothing refreshes those clocks from the application side.
 *
 * Both hops were wrong, and only one was suspected. ingress-nginx defaults `proxy_read_timeout` to 60s,
 * and `svelte-adapter-bun` defaults Bun's `idleTimeout` to 10s — so on kind the streams were dying every
 * ~12s with "upstream prematurely closed connection" in the nginx log while the annotation everyone was
 * looking at said 3600. Raising one without the other buys nothing: the smaller wins.
 *
 * This gate is why the numbers cannot drift apart again. It reads the chart, not a comment.
 */

const NGINX_DEFAULT_READ_TIMEOUT_S = 60;
const values = readFileSync(resolve(REPO_ROOT, 'chart/values.yaml'), 'utf8');
const helpers = readFileSync(resolve(REPO_ROOT, 'chart/templates/_helpers.tpl'), 'utf8');

const proxyReadTimeout = Number(
	/nginx\.ingress\.kubernetes\.io\/proxy-read-timeout:\s*"?(\d+)"?/.exec(values)?.[1],
);
const idleTimeout = Number(/idleTimeoutSeconds:\s*(\d+)/.exec(values)?.[1]);

describe('a live query survives both idle timeouts', () => {
	it('the Ingress overrides nginx’s 60s proxy-read-timeout', () => {
		expect(proxyReadTimeout).toBeGreaterThan(NGINX_DEFAULT_READ_TIMEOUT_S);
	});

	it('the zone server overrides the adapter’s 10s idle timeout', () => {
		// The env name is the adapter's, not ours: `parseInt(env("IDLE_TIMEOUT", "10"), 10)`.
		expect(helpers).toContain('name: IDLE_TIMEOUT');
		expect(idleTimeout).toBeGreaterThan(NGINX_DEFAULT_READ_TIMEOUT_S);
	});

	it('the zone server’s timeout is not the binding constraint', () => {
		// The proxy is allowed to hold longer than the origin only if the origin is not the one cutting
		// first. Whichever is smaller is the real lifetime of every live subscription in the estate.
		expect(Math.min(proxyReadTimeout, idleTimeout)).toBeGreaterThan(NGINX_DEFAULT_READ_TIMEOUT_S);
	});

	it('IDLE_TIMEOUT stays within Bun’s ceiling', () => {
		// Bun.serve rejects an idleTimeout above 255, and 0 disables reaping entirely — a wedged client
		// would then hold its socket for ever. A stream that must outlive 255s of silence needs a
		// keepalive in the payload, not a larger number here.
		expect(idleTimeout).toBeGreaterThan(0);
		expect(idleTimeout).toBeLessThanOrEqual(255);
	});
});
