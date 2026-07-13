// See https://svelte.dev/docs/kit/types#app.d.ts
import type { Session } from "$lib/server/oidc";

declare global {
	namespace App {
		// interface Error {}
		interface Locals {
			/** The signed-in user's session (tokens + claims), or null when auth is off / unauthenticated. */
			session: Session | null;
			/** Whether OIDC is configured (drives the UI's sign-in affordance). */
			authEnabled: boolean;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
