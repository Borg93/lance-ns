import { env } from '$env/dynamic/private';
import { KEEP_API_PREFIX, makeBackendProxy } from '@rask/api/bff';

// Same-origin read proxy to the VIEWER service — the media-plane catch-all (documents,
// media/thumbnail/chunk-frame streams, atlas, graph, voice, topics, datasets, health).
// GET-only, forwarding the signed-in user's bearer so the backend can attribute the
// caller (per-user VERIFICATION inside the media services is backend follow-up work).
// Range rides through (media seeking) and the upstream's response headers pass back
// (content-range/accept-ranges/cache-control) — single-sourced in @rask/api/bff.
// The search + annotator domains have their own more-specific routes beside this one.
const VIEWER_API = env.VIEWER_API ?? 'http://localhost:8101';

export const GET = makeBackendProxy({
	backendUrl: VIEWER_API,
	stripPrefix: KEEP_API_PREFIX,
	forwardRequestHeaders: ['range', 'accept', 'if-none-match', 'if-modified-since'],
	forwardResponseHeaders: true,
});
