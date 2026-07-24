import { Database } from '@lucide/svelte';

/** All lucide icons share one component signature, so any icon's type fits. */
export type IconComponent = typeof Database;

/** A leaf route inside the CURRENT zone's sidebar — same-zone (soft nav) unless `reload` says
 *  otherwise. */
export type ZoneNavLeaf = {
	title: string;
	/** ABSOLUTE, domain-relative href (e.g. /data/tables). */
	href: string;
	/** Active predicate vs the FULL pathname. */
	match: (p: string) => boolean;
	icon?: IconComponent;
	/** True for a leaf that leaves this zone's route manifest (e.g. media's Annotate → /annotator):
	 *  the sidebar link then hard-navigates (data-sveltekit-reload) instead of soft-routing. */
	reload?: boolean;
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

/** One sub-area inside a zone's navbar panel — a first-class view of that zone, with a one-line
 *  description so the panel explains the estate instead of just listing words. */
export type TopNavItem = { title: string; href: string; description: string };

/** One top-navbar entry — a whole microfrontend zone (cross-zone = hard nav). */
export type TopNavEntry = {
	title: string;
	href: string;
	match: (p: string) => boolean;
	/** The zone's sub-areas. Present → the navbar renders a NavigationMenu trigger opening a panel
	 *  of these; absent → a plain link, because the zone has a single surface and a dropdown with
	 *  one row in it would be noise. Deliberately a SUBSET of the zone's own sidebar (`ZoneNav`):
	 *  this is the cross-zone jump list, not a mirror of in-zone navigation. */
	items?: TopNavItem[];
};

const DATA_ITEMS: TopNavItem[] = [
	{
		title: 'Projects',
		href: '/data/projects',
		description: 'Tenants, their warehouses and their members.',
	},
	{ title: 'Tables', href: '/data/tables', description: 'The governed table registry.' },
	{
		title: 'Namespaces',
		href: '/data/namespaces',
		description: 'Medallion namespaces and their maintenance policies.',
	},
	{
		title: 'Warehouses',
		href: '/data/warehouses',
		description: 'Storage bindings — one bucket per project.',
	},
];

const LINEAGE_ITEMS: TopNavItem[] = [
	{
		title: 'Datasets',
		href: '/lineage/datasets',
		description: 'Every dataset the cascade has read or written.',
	},
	{
		title: 'Jobs',
		href: '/lineage/jobs',
		description: 'The compute identities that produce them.',
	},
	{
		title: 'Runs',
		href: '/lineage/runs',
		description: 'Individual executions, with state and errors.',
	},
	{
		title: 'Columns',
		href: '/lineage/columns',
		description: 'Field-level lineage across the estate.',
	},
	{ title: 'Graph', href: '/lineage', description: 'The whole medallion DAG on one canvas.' },
];

const MEDIA_ITEMS: TopNavItem[] = [
	{ title: 'Search', href: '/media', description: 'Semantic search over the corpus.' },
	{ title: 'Atlas', href: '/media/atlas', description: 'The embedding map of the corpus.' },
	{ title: 'Tree', href: '/media/tree', description: 'The corpus by topic hierarchy.' },
	{ title: 'Graph', href: '/media/graph', description: 'Relations between media entities.' },
	{ title: 'Workflow', href: '/media/workflow', description: 'The derivation pipeline.' },
];

const ADMIN_ITEMS: TopNavItem[] = [
	{
		title: 'Tenants',
		href: '/admin/tenants',
		description: 'Warehouses per project, and who administers them.',
	},
	{ title: 'Audit', href: '/admin/audit', description: 'The compliance trail — who did what.' },
	{ title: 'Streams', href: '/admin/streams', description: 'JetStream consumers and their lag.' },
	{ title: 'DLQ', href: '/admin/dlq', description: 'Dead-lettered lineage runs, with replay.' },
	{ title: 'Events', href: '/admin/events', description: 'The live control-event feed.' },
	{
		title: 'Access',
		href: '/admin/access',
		description: 'The FGA workbench: check, tuples, graph.',
	},
];

/**
 * The top-navbar IA: one entry per microfrontend zone (cohesion, low coupling — each zone is a
 * SEPARATE SvelteKit app under `/<domain>`; Home owns the origin root). The zones-in-sidebar list
 * this replaces is gone: the sidebar now renders only the CURRENT zone's own routes (`ZoneNav`).
 *
 * A zone with sub-areas carries `items`, and the navbar renders it as a NavigationMenu trigger with
 * a panel — so the estate's shape is reachable from any zone in one hop instead of landing on a
 * zone root and hunting through its sidebar. Zones with a single surface stay plain links.
 *
 * Admin appends ONLY for an estate admin (`me.estate_admin` from the frozen `/v1/me` contract) —
 * fail-closed: an unresolved/absent `me` renders the base entries. Access is NOT a top-level
 * entry: it lives inside the admin zone (/admin/access), so Admin covers the whole /admin subtree
 * here and Access appears only as one row of Admin's panel.
 */
export function topNav(estateAdmin: boolean): TopNavEntry[] {
	const entries: TopNavEntry[] = [
		{ title: 'Home', href: '/', match: (p) => norm(p) === '/' },
		{ title: 'Data', href: '/data', match: under('/data'), items: DATA_ITEMS },
		{ title: 'Lineage', href: '/lineage', match: under('/lineage'), items: LINEAGE_ITEMS },
		{ title: 'Models', href: '/models', match: under('/models') },
		{ title: 'Media', href: '/media', match: under('/media'), items: MEDIA_ITEMS },
		{ title: 'Annotator', href: '/annotator', match: under('/annotator') },
	];
	if (estateAdmin) {
		entries.push({ title: 'Admin', href: '/admin', match: under('/admin'), items: ADMIN_ITEMS });
	}
	return entries;
}

/** The first path segment = the owning zone ('' = the home zone at the origin root). A link whose
 *  zone differs from the current pathname's leaves this app's route manifest, so it must hard-nav
 *  (data-sveltekit-reload); same-zone links stay soft for SPA speed. */
export const zoneOf = (p: string) => p.split('/').filter(Boolean)[0] ?? '';

const prefetched = new Set<string>();

/** Warm a CROSS-ZONE target document on intent (hover/focus). SvelteKit's own
 *  `data-sveltekit-preload-data` only helps same-zone soft navs — a cross-zone link is a full
 *  document load into another app — so we drop a `<link rel="prefetch">` for the target instead.
 *  Honest scope: this is a browser HINT that warms the HTTP cache for the target zone's document
 *  (Chromium and Firefox honor it; Safari does not), so the hard nav paints from cache instead of
 *  a cold round-trip. Once per href per document; SSR no-op. */
export function prefetchDocument(href: string) {
	if (typeof document === 'undefined' || prefetched.has(href)) return;
	prefetched.add(href);
	const link = document.createElement('link');
	link.rel = 'prefetch';
	link.href = href;
	document.head.append(link);
}

/** `{@attach}` factory: warm `href` (prefetchDocument) on pointerenter/focus. Native listeners on
 *  purpose — inside a `child({ props })` snippet the component's own spread props may carry their
 *  own pointer handlers (e.g. the sidebar MenuButton's tooltip trigger), and a plain
 *  `onpointerenter` attribute would be overwritten by (or overwrite) them. */
export function prefetchOnIntent(href: string) {
	return (el: HTMLElement) => {
		const warm = () => prefetchDocument(href);
		el.addEventListener('pointerenter', warm);
		el.addEventListener('focus', warm);
		return () => {
			el.removeEventListener('pointerenter', warm);
			el.removeEventListener('focus', warm);
		};
	};
}
