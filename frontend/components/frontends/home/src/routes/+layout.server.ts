import { env } from '$env/dynamic/private';
import type { LayoutServerLoad } from './$types';
import { sessionToUser } from '@rask/api/bff';
import { fetchMe } from '@rask/api';

const CATALOG_API = env.CATALOG_API ?? 'http://localhost:2333';

// Surface the signed-in identity + the auth-enabled flag to the shared TopNavbar. `user` is the
// single-sourced sessionToUser projection ("auth is identical in every MFE"); `me` is the frozen
// /v1/me contract fetched BFF-side with the session bearer — NESTED under `streamed` so SvelteKit
// streams it and the navbar can render skeletons until it resolves (null = signed out / catalog
// unreachable → base entries only, fail-closed on the admin surfaces).
export const load: LayoutServerLoad = ({ locals }) => ({
	user: sessionToUser(locals.session),
	authEnabled: locals.authEnabled,
	streamed: {
		me: fetchMe({ catalogUrl: CATALOG_API, accessToken: locals.session?.accessToken }),
	},
});
