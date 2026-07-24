import { Boxes, Database, FolderKanban, Warehouse } from '@lucide/svelte';
import { seg, type ZoneNav } from '@rask/ui/shell';

// The data zone's OWN sidebar routes (the shared shell renders exactly what a zone passes — the
// cross-zone list lives in the top navbar). Hrefs are absolute domain paths: the zone is served
// under its `/data` base both standalone (dev/e2e) and behind the ingress, so `/data/...` is
// correct everywhere, and `seg` keeps a leaf lit across its nested detail pages.
export const DATA_ZONE_NAV: ZoneNav = {
	title: 'Data',
	leaves: [
		{ title: 'Projects', href: '/data/projects', match: seg('/data/projects'), icon: FolderKanban },
		{ title: 'Tables', href: '/data/tables', match: seg('/data/tables'), icon: Database },
		{ title: 'Namespaces', href: '/data/namespaces', match: seg('/data/namespaces'), icon: Boxes },
		{
			title: 'Warehouses',
			href: '/data/warehouses',
			match: seg('/data/warehouses'),
			icon: Warehouse,
		},
	],
};
