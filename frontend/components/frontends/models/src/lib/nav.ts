import { FlaskConical, Package, Workflow } from '@lucide/svelte';
import { exact, seg, type ZoneNav } from '@rask/ui/shell';

// The models zone's OWN sidebar routes. Registry sits at the zone root, so it matches `exact`
// (a `seg` there would light it up on every sibling sub-route); the sub-pages use `seg`.
export const MODELS_ZONE_NAV: ZoneNav = {
	title: 'Models',
	leaves: [
		{ title: 'Registry', href: '/models', match: exact('/models'), icon: Package },
		{ title: 'Pipeline', href: '/models/pipeline', match: seg('/models/pipeline'), icon: Workflow },
		{
			title: 'Experiments',
			href: '/models/experiments',
			match: seg('/models/experiments'),
			icon: FlaskConical,
		},
	],
};
