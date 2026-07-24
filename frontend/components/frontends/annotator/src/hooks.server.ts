import { env } from '$env/dynamic/private';
import { makeOidcConfig, makeSessionHandle } from '@rask/api/bff';

// Per-request session hydration from the sealed OIDC cookie (single-sourced in @rask/api/bff), so
// the estate navbar's identity + /capi/v1/me pass-through work in this zone too. No-op when OIDC is
// unconfigured (the zone runs auth-off — dev servers and hermetic e2e are unchanged).
export const handle = makeSessionHandle(makeOidcConfig(env));
