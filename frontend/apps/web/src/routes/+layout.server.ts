/**
 * Expose the auth state to every page: who's signed in (name/email only — never the token) and whether
 * a sign-in affordance should show at all. `locals` is populated by `hooks.server.ts`.
 */
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = ({ locals }) => {
	return {
		authEnabled: locals.authEnabled,
		user: locals.session ? { name: locals.session.name, email: locals.session.email } : null
	};
};
