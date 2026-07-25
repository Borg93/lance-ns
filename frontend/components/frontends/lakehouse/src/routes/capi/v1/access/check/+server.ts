import { env } from '$env/dynamic/private';
import { makeBackendProxy } from '@repo/api/bff';

// The FGA workbench's check probe: POST /v1/access/check → a live OpenFGA Check verdict on any
// (user, relation, object) triple. Estate-admin gated BY THE CATALOG (probing the graph == disclosing
// it); this route only bearer-forwards the signed-in user's session.
const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

export const POST = makeBackendProxy({ backendUrl: CATALOG_API, stripPrefix: /^\/capi/ });
