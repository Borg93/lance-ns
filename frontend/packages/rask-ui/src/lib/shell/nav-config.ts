import { Database } from '@lucide/svelte';

/** All lucide icons share one component signature, so any icon's type fits. */
export type IconComponent = typeof Database;

/** A leaf route inside the CURRENT zone's sidebar — always same-zone (soft nav). */
export type ZoneNavLeaf = {
	title: string;
	/** ABSOLUTE, domain-relative href (e.g. /data/tables). */
	href: string;
	/** Active predicate vs the FULL pathname. */
	match: (p: string) => boolean;
	icon?: IconComponent;
};

/** The per-zone sidebar config: each zone passes ITS OWN routes to the shared AppShell. The zone
 *  list itself lives in the top navbar (`topNav`) — the sidebar never renders other zones. */
export type ZoneNav = {
	/** The zone's display name — the sidebar group label (e.g. "Data"). */
	title: string;
	leaves: ZoneNavLeaf[];
};

/** A selectable project — the sidebar header switcher. One implicit "default" today. */
export type Project = { name: string; subtitle?: string };

/** The navbar profile identity — populated from the OIDC session (per-zone +layout). */
export type NavUser = { name: string; email?: string; initials?: string };

/** One project membership row from `/v1/me` — the tenant and the caller's role in it. */
export type MeProject = { project: string; role: 'admin' | 'member' };

/** The frozen `GET /v1/me` identity contract, mirrored structurally from @rask/api (the shared shell
 *  never imports app data — same seam as `NavUser`): any verified caller's sub/name/email, whether
 *  they hold the estate-admin privilege, and their project memberships. */
export type Me = {
	sub: string;
	name: string | null;
	email: string | null;
	estate_admin: boolean;
	projects: MeProject[];
};

/** Drop a single trailing slash (except on root "/"). A zone served under a base path reports its ROOT
 *  as `page.url.pathname === '/models/'` (trailing slash), which would fail an exact compare against
 *  '/models'; normalizing here makes every matcher trailing-slash-robust. */
export const norm = (p: string) => (p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p);
/** prefix-segment match: active when the path equals the href or is nested under it. */
export const seg = (href: string) => (p: string) =>
	norm(p) === href || norm(p).startsWith(href + '/');
/** exact match: active ONLY on this exact path. Used for a root leaf whose href equals its own
 *  zone's href (e.g. Registry=/models, Graph=/lineage) — `seg` there would over-match every sibling
 *  sub-route (/models/pipeline would light up Registry too), so those leaves match exactly. */
export const exact = (href: string) => (p: string) => norm(p) === href;
/** domain match: active when the path is under any of the given prefixes. */
export const under =
	(...prefixes: string[]) =>
	(p: string) =>
		prefixes.some((pre) => norm(p) === pre || norm(p).startsWith(pre + '/'));

/** One top-navbar entry — a whole microfrontend zone (cross-zone = hard nav). */
export type TopNavEntry = {
	title: string;
	href: string;
	match: (p: string) => boolean;
};

/**
 * The top-navbar IA: one entry per microfrontend zone (cohesion, low coupling — each zone is a
 * SEPARATE SvelteKit app under `/<domain>`; Home owns the origin root). The zones-in-sidebar list
 * this replaces is gone: the sidebar now renders only the CURRENT zone's own routes (`ZoneNav`).
 *
 * Admin + Access append ONLY for an estate admin (`me.estate_admin` from the frozen `/v1/me`
 * contract) — fail-closed: an unresolved/absent `me` renders the base entries. Access is the
 * estate access-review surface inside the admin zone, so Admin's own match excludes it (one lit
 * entry per route).
 */
export function topNav(estateAdmin: boolean): TopNavEntry[] {
	const entries: TopNavEntry[] = [
		{ title: 'Home', href: '/', match: (p) => norm(p) === '/' },
		{ title: 'Data', href: '/data', match: under('/data') },
		{ title: 'Lineage', href: '/lineage', match: under('/lineage') },
		{ title: 'Models', href: '/models', match: under('/models') },
		{ title: 'Media', href: '/media', match: under('/media') },
		{ title: 'Annotator', href: '/annotator', match: under('/annotator') },
	];
	if (estateAdmin) {
		entries.push(
			{
				title: 'Admin',
				href: '/admin',
				match: (p) => under('/admin')(p) && !seg('/admin/access')(p),
			},
			{ title: 'Access', href: '/admin/access', match: seg('/admin/access') },
		);
	}
	return entries;
}

/** The first path segment = the owning zone ('' = the home zone at the origin root). A link whose
 *  zone differs from the current pathname's leaves this app's route manifest, so it must hard-nav
 *  (data-sveltekit-reload); same-zone links stay soft for SPA speed. */
export const zoneOf = (p: string) => p.split('/').filter(Boolean)[0] ?? '';
