/** Per-request timeout — a hung backend must not stack poll ticks (§2 perf, 2026-07-11). */
export const FETCH_TIMEOUT_MS = 8000;

// AbortSignal.timeout needs Safari 16+/Chrome 103+; vite transpiles syntax, not APIs — on an older
// browser the missing function would throw inside a fetcher's catch and the app would silently render
// permanently "offline". Feature-detect with an AbortController fallback (review 2026-07-11).
export function timeoutSignal(ms: number): AbortSignal {
	if (typeof AbortSignal.timeout === "function") return AbortSignal.timeout(ms);
	const controller = new AbortController();
	setTimeout(() => controller.abort(), ms);
	return controller.signal;
}
