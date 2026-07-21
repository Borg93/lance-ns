import { env } from '$env/dynamic/private';
import { makeGatewayHandleFetch } from '@rask/api';
import { makeOidcConfig, makeSessionHandle } from '@rask/api/bff';

// Per-request session hydration from the sealed OIDC cookie (single-sourced in @rask/api/bff); no-op when
// OIDC is unconfigured (the zone runs auth-off). Login/callback routes + per-user proxies land in P3.
export const handle = makeSessionHandle(makeOidcConfig(env));

// SSR /api/* → the in-cluster gateway (single-sourced in @rask/api/gateway). The chart sets
// LANCE_GATEWAY_URL in-cluster; dev defaults to the local gateway.
export const handleFetch = makeGatewayHandleFetch(env.LANCE_GATEWAY_URL ?? 'http://localhost:8001');
