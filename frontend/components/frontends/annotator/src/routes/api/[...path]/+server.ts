import { env } from '$env/dynamic/private';
import { KEEP_API_PREFIX, makeBackendProxy } from '@rask/api/bff';

// Same-origin read proxy to the VIEWER service — the media streams this zone renders
// (chunk-frame images, /api/media audio+video for the temporal viewers). GET-only,
// forwarding the signed-in user's bearer so the backend can attribute the caller
// (per-user VERIFICATION inside the media services is backend follow-up work). Range
// rides through (seeking) and the upstream's response headers pass back — single-
// sourced in @rask/api/bff. The annotations/assist/jobs/search domains have their own
// more-specific routes beside this one (the old server.ts zone map, per-route).
const VIEWER_API = env.VIEWER_API ?? 'http://localhost:8101';

export const GET = makeBackendProxy({
	backendUrl: VIEWER_API,
	stripPrefix: KEEP_API_PREFIX,
	forwardRequestHeaders: ['range', 'accept', 'if-none-match', 'if-modified-since'],
	forwardResponseHeaders: true,
});
