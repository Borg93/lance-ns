import { env } from '$env/dynamic/private';
import { makeZoneHooks } from '@rask/api/bff';

// Per-request session hydration from the sealed OIDC cookie (single-sourced in @rask/api/bff), so the
// estate navbar's identity + /capi/v1/me pass-through work in this zone too. No gateway handleFetch:
// this zone reaches the media services through its OWN BFF routes, not the lineage gateway.
export const { handle } = makeZoneHooks(env);
