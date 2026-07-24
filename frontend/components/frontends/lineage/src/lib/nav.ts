import { Activity, Boxes, Columns3, Cpu, Network } from '@lucide/svelte';
import { exact, seg, type ZoneNav } from '@rask/ui/shell';

// The lineage zone's OWN sidebar routes (Marquez-parity IA): the four first-class views —
// Datasets / Jobs / Runs / Columns — plus the DAG explorer at the zone root. Hrefs are absolute
// domain paths (the zone is served under its `/lineage` base both standalone and behind the
// ingress); `seg` keeps a list leaf lit across its nested detail pages.
export const LINEAGE_ZONE_NAV: ZoneNav = {
	title: 'Lineage',
	leaves: [
		{
			title: 'Datasets',
			href: '/lineage/datasets',
			match: seg('/lineage/datasets'),
			icon: Boxes,
		},
		{ title: 'Jobs', href: '/lineage/jobs', match: seg('/lineage/jobs'), icon: Cpu },
		{ title: 'Runs', href: '/lineage/runs', match: seg('/lineage/runs'), icon: Activity },
		{
			title: 'Columns',
			href: '/lineage/columns',
			match: seg('/lineage/columns'),
			icon: Columns3,
		},
		{ title: 'Graph', href: '/lineage', match: exact('/lineage'), icon: Network },
	],
};
