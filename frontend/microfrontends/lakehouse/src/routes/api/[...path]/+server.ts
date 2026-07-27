import { env } from '$env/dynamic/private';
import { makeLineageProxy } from '@repo/api/bff';

// Same-origin, GET-only pass-through to the LINEAGE service (the /capi proxy covers catalog), with the
// READ-only service-credential fallback. Single-sourced in @repo/api/bff.
export const GET = makeLineageProxy(env);
