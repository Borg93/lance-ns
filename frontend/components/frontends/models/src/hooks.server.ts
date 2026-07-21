import type { HandleFetch } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { makeGatewayHandleFetch } from '@rask/api';

// Single-sourced SSR gateway rewrite (see @rask/api/gateway). Dev defaults to the
// local gateway; the chart sets LANCE_GATEWAY_URL in-cluster. P2 folds the OIDC
// session handle + FGA bearer-forwarding into the same @rask/api seam.
export const handleFetch: HandleFetch = makeGatewayHandleFetch(
	env.LANCE_GATEWAY_URL ?? 'http://localhost:8001',
);
