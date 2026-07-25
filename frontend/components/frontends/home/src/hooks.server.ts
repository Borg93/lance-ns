import { env } from '$env/dynamic/private';
import { makeZoneHooks } from '@rask/api/bff';

// Per-request session hydration from the sealed OIDC cookie + the SSR `/api/*` → in-cluster gateway
// rewrite, both single-sourced in @rask/api/bff. No-op when OIDC is unconfigured (the zone runs
// auth-off). The chart sets LANCE_GATEWAY_URL in-cluster; dev defaults to the local gateway.
export const { handle, handleFetch } = makeZoneHooks(env, { gateway: true });
