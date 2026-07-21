import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@rask/api/bff';

// Same-origin proxy to the LINEAGE service (the /capi proxy covers catalog). GET-only, forwards the
// signed-in user's bearer; a READ-only service-credential fallback lets a governed stack serve reads
// without a per-user login (never on writes — the confused-deputy guard). Single-sourced in @rask/api/bff.
const LINEAGE_API = env.LINEAGE_API ?? 'http://localhost:8001';

export const GET = makeBackendProxy({
	backendUrl: LINEAGE_API,
	stripPrefix: /^\/api/,
	serviceToken: env.LINEAGE_SERVICE_TOKEN,
	serviceId: env.LINEAGE_SERVICE_ID,
});
