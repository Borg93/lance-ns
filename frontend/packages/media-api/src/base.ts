/**
 * The media-plane API base — where `/api/*` lives for the CURRENT zone.
 *
 * Every media/annotator fetch is same-origin against the zone's OWN BFF proxy routes
 * (`/<zone>/api/*` → viewer/search/annotator, bearer-forwarded), so the path must carry
 * the zone's base. The zones set it once at layout-module init (`setApiBase(base)` with
 * SvelteKit's `$app/paths` base); the default `''` keeps root-absolute `/api/*` for
 * unbased consumers (unit tests, the standalone dev servers before the layout runs).
 * Framework-agnostic on purpose — this package never imports `$app/*`.
 */

let apiBase = '';

/** Set the base path prefixed to every `/api/*` URL this package (and @repo/labeling)
 *  builds — the zone's SvelteKit `base`. Idempotent; trailing slash is normalized. */
export function setApiBase(b: string): void {
	apiBase = b.replace(/\/$/, '');
}

/** A root-relative media-plane URL under the configured zone base: `apiUrl('/api/health')`
 *  → `/media/api/health` once the media zone has called `setApiBase('/media')`. */
export function apiUrl(path: string): string {
	return `${apiBase}${path}`;
}
