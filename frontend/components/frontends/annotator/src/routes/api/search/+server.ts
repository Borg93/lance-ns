import { env } from '$env/dynamic/private';
import { KEEP_API_PREFIX, makeBackendProxy } from '@rask/api/bff';

// Same-origin read proxy to the SEARCH service — the /api/search leg of the old zone
// map, kept so a read-plane deep-link resolved inside this zone still answers. GET-only
// here: this app submits no image-search POST (that write-shaped read is enumerated in
// the media zone, which owns the search surface).
const SEARCH_API = env.SEARCH_API ?? 'http://localhost:8102';

export const GET = makeBackendProxy({ backendUrl: SEARCH_API, stripPrefix: KEEP_API_PREFIX });
