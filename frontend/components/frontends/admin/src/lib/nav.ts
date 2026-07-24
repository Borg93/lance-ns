import { Building2, Inbox, Layers, Radio, ScrollText, ShieldCheck } from '@lucide/svelte';
import { seg, type ZoneNav } from '@rask/ui/shell';

// The admin zone's OWN sidebar routes. Access is the estate access-review surface (playground +
// grants) — it also has its own top-navbar entry, mirrored here so the sidebar is complete.
export const ADMIN_ZONE_NAV: ZoneNav = {
	title: 'Admin',
	leaves: [
		{ title: 'Tenants', href: '/admin/tenants', match: seg('/admin/tenants'), icon: Building2 },
		{ title: 'Audit', href: '/admin/audit', match: seg('/admin/audit'), icon: ScrollText },
		{ title: 'Streams', href: '/admin/streams', match: seg('/admin/streams'), icon: Layers },
		{ title: 'DLQ', href: '/admin/dlq', match: seg('/admin/dlq'), icon: Inbox },
		{ title: 'Events', href: '/admin/events', match: seg('/admin/events'), icon: Radio },
		{ title: 'Access', href: '/admin/access', match: seg('/admin/access'), icon: ShieldCheck },
	],
};
