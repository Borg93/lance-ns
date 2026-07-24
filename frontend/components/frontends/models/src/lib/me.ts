import { MeSchema, parse, type Me } from '@rask/api';
import { bffPath, FETCH_TIMEOUT_MS, timeoutSignal } from './http';

export type { Me };

/**
 * Browser-side `/v1/me` through THIS zone's bearer-forwarding BFF pass-through (`/capi/v1/me`).
 * Same degrade posture as @rask/api's server-side `fetchMe`: `null` on ANY failure (signed out,
 * 401, outage, timeout, contract drift) — the navbar then renders the base entry set, fail-closed
 * on the admin surfaces. Browser-side on purpose: the session bearer lives in the sealed cookie
 * the BFF holds, and a same-origin fetch keeps the identity seam mockable in hermetic e2e.
 */
export async function fetchMeViaBff(): Promise<Me | null> {
	try {
		const res = await fetch(bffPath('/capi/v1/me'), { signal: timeoutSignal(FETCH_TIMEOUT_MS) });
		if (!res.ok) return null;
		return parse(MeSchema, await res.json());
	} catch {
		return null;
	}
}
