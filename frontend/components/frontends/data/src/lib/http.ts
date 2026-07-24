import { base as appBase } from '$app/paths';

/** Per-request timeout — a hung backend must not stack poll ticks (§2 perf, 2026-07-11). */
export const FETCH_TIMEOUT_MS = 8000;

// AbortSignal.timeout needs Safari 16+/Chrome 103+; vite transpiles syntax, not APIs — on an older
// browser the missing function would throw inside a fetcher's catch and the app would silently render
// permanently "offline". Feature-detect with an AbortController fallback (review 2026-07-11).
export function timeoutSignal(ms: number): AbortSignal {
	if (typeof AbortSignal.timeout === 'function') return AbortSignal.timeout(ms);
	const controller = new AbortController();
	setTimeout(() => controller.abort(), ms);
	return controller.signal;
}

/** Prefix the SvelteKit base path to an absolute same-origin BFF path (`/api/…`, `/capi/…`,
 * `/medallion/…`). This zone is served UNDER its base (`/data`, `/admin`, …) and its BFF proxy routes live
 * there, so a browser call MUST carry the base — the Ingress path-routes `/<zone>` to this zone, and a bare
 * `/capi` 404s (it never reaches this zone). Bare paths worked in apps/web only because it had no base. */
export const bffPath = (p: string): string => `${appBase}${p}`;

/** A fetch outcome that keeps the HTTP status — writes need 401 ("sign in") ≠ 403 (rung denial) ≠ 0
 * (offline), which getJSON-style null-on-error cannot express. Shared by the lineage + catalog clients. */
export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string };

/** One status-aware JSON request against a same-origin BFF base ("/api" or "/capi"), base-path-aware. */
export async function requestJSON<T>(
	base: string,
	path: string,
	init?: RequestInit,
): Promise<ApiResult<T>> {
	try {
		const res = await fetch(`${bffPath(base)}/${path}`, {
			...init,
			signal: timeoutSignal(FETCH_TIMEOUT_MS),
		});
		const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
		if (!res.ok) {
			const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`;
			return { ok: false, status: res.status, detail };
		}
		return { ok: true, data: body as T };
	} catch (err) {
		return { ok: false, status: 0, detail: String(err) };
	}
}

/** The binary sibling of requestJSON — for BFF responses that are NOT JSON (the table-preview
 * Arrow-IPC file). Success hands back the raw bytes; a failure still reads the JSON `detail`
 * (error responses stay JSON on every BFF route), with the same 401 ≠ 403 ≠ 0 status split. */
export async function requestBinary(
	base: string,
	path: string,
	init?: RequestInit,
): Promise<ApiResult<ArrayBuffer>> {
	try {
		const res = await fetch(`${bffPath(base)}/${path}`, {
			...init,
			signal: timeoutSignal(FETCH_TIMEOUT_MS),
		});
		if (!res.ok) {
			const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
			const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`;
			return { ok: false, status: res.status, detail };
		}
		return { ok: true, data: await res.arrayBuffer() };
	} catch (err) {
		return { ok: false, status: 0, detail: String(err) };
	}
}
