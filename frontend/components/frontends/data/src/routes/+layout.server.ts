import type { LayoutServerLoad } from './$types';
import { sessionToUser } from '@rask/api/bff';

// Surface the signed-in identity + the auth-enabled flag to the shared AppShell (nav-user renders Sign in
// / Sign out). Single-sourced via @rask/api's sessionToUser so every zone derives the SAME user — "auth is
// identical in every MFE". No-op shape on an auth-off stack: user is null, authEnabled false.
export const load: LayoutServerLoad = ({ locals }) => ({
	user: sessionToUser(locals.session),
	authEnabled: locals.authEnabled,
});
