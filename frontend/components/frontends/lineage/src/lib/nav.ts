import { Network } from '@lucide/svelte';
import { exact, type ZoneNav } from '@rask/ui/shell';

// The lineage zone's OWN sidebar routes — one leaf today: the explorer graph at the zone root
// (`exact`, so a future sibling sub-route doesn't keep it lit).
export const LINEAGE_ZONE_NAV: ZoneNav = {
	title: 'Lineage',
	leaves: [{ title: 'Graph', href: '/lineage', match: exact('/lineage'), icon: Network }],
};
