import { Database, GitBranch, Boxes, ShieldCheck } from '@lucide/svelte';

/** All lucide icons share one component signature, so any icon's type fits. */
type IconComponent = typeof Database;

/** A leaf route inside a collapsible domain item. */
export type NavLeaf = {
	title: string;
	/** ABSOLUTE, domain-relative href (e.g. /data/tables). */
	href: string;
	/** Active predicate vs the FULL pathname. */
	match: (p: string) => boolean;
};

/** A top-level sidebar item — a domain. With `items` it renders as a collapsible
 *  accordion (sidebar-07 NavMain); without, as a direct link. */
export type NavItem = {
	title: string;
	icon: IconComponent;
	href: string;
	match: (p: string) => boolean;
	items?: NavLeaf[];
};

/** A selectable project — the sidebar header switcher. One implicit "default" today. */
export type Project = { name: string; subtitle?: string };

/** The footer profile identity — populated from the OIDC session (per-zone +layout). */
export type NavUser = { name: string; email?: string; initials?: string };

/** Drop a single trailing slash (except on root "/"). A zone served under a base path reports its ROOT
 *  as `page.url.pathname === '/models/'` (trailing slash), which would fail an exact compare against
 *  '/models'; normalizing here makes every matcher trailing-slash-robust. */
const norm = (p: string) => (p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p);
/** prefix-segment match: active when the path equals the href or is nested under it. */
const seg = (href: string) => (p: string) => norm(p) === href || norm(p).startsWith(href + '/');
/** exact match: active ONLY on this exact path. Used for a root leaf whose href equals its own
 *  domain's href (e.g. Registry=/models, Graph=/lineage) — `seg` there would over-match every sibling
 *  sub-route (/models/pipeline would light up Registry too), so those leaves match exactly. */
const exact = (href: string) => (p: string) => norm(p) === href;
/** domain match: active when the path is under any of the given prefixes. */
const under =
	(...prefixes: string[]) =>
	(p: string) =>
		prefixes.some((pre) => norm(p) === pre || norm(p).startsWith(pre + '/'));

/**
 * The lance micro-frontend zones (cohesion, low coupling). Each domain is a SEPARATE
 * SvelteKit app under `/<domain>`; every href is domain-relative and cross-zone nav is a
 * full-document reload (the shared shell sets data-sveltekit-reload; the cross-zone-reload
 * eslint rule guards hand-written links). The sidebar renders identically in every zone —
 * one AppShell, zero drift.
 */
export function navMain(): NavItem[] {
	const b = '';
	return [
		{
			title: 'Data',
			icon: Database,
			href: `${b}/data`,
			match: under(`${b}/data`),
			items: [
				{ title: 'Tables', href: `${b}/data/tables`, match: seg(`${b}/data/tables`) },
				{ title: 'Namespaces', href: `${b}/data/namespaces`, match: seg(`${b}/data/namespaces`) },
				{ title: 'Warehouses', href: `${b}/data/warehouses`, match: seg(`${b}/data/warehouses`) },
			],
		},
		{
			title: 'Lineage',
			icon: GitBranch,
			href: `${b}/lineage`,
			match: under(`${b}/lineage`),
			items: [
				{ title: 'Graph', href: `${b}/lineage`, match: exact(`${b}/lineage`) },
				{ title: 'Runs', href: `${b}/lineage/runs`, match: seg(`${b}/lineage/runs`) },
				{ title: 'Events', href: `${b}/lineage/events`, match: seg(`${b}/lineage/events`) },
			],
		},
		{
			title: 'Models',
			icon: Boxes,
			href: `${b}/models`,
			match: under(`${b}/models`),
			items: [
				{ title: 'Registry', href: `${b}/models`, match: exact(`${b}/models`) },
				{
					title: 'Experiments',
					href: `${b}/models/experiments`,
					match: seg(`${b}/models/experiments`),
				},
				{ title: 'Pipeline', href: `${b}/models/pipeline`, match: seg(`${b}/models/pipeline`) },
			],
		},
		{
			title: 'Admin',
			icon: ShieldCheck,
			href: `${b}/admin`,
			match: under(`${b}/admin`),
			items: [
				{ title: 'Audit', href: `${b}/admin/audit`, match: seg(`${b}/admin/audit`) },
				{ title: 'DLQ', href: `${b}/admin/dlq`, match: seg(`${b}/admin/dlq`) },
				{ title: 'Access', href: `${b}/admin/access`, match: seg(`${b}/admin/access`) },
			],
		},
	];
}
