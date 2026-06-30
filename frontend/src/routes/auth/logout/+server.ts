/**
 * Clear the session cookie and return home. Accept POST (the form-driven path, CSRF-safer) and GET (a
 * plain link), since this demo has no other state-changing surface to protect.
 */
import { redirect, type RequestHandler } from '@sveltejs/kit';
import { SESSION_COOKIE } from '$lib/server/oidc';

const signOut: RequestHandler = ({ cookies }) => {
	cookies.delete(SESSION_COOKIE, { path: '/' });
	redirect(302, '/');
};

export const POST = signOut;
export const GET = signOut;
