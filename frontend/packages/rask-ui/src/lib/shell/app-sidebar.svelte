<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Sidebar from '../components/sidebar/index.js';
	import ProjectSwitcher from './project-switcher.svelte';
	import ZoneNav from './zone-nav.svelte';
	import type { Project, ZoneNav as ZoneNavConfig } from './nav-config.js';

	// The zone-scoped sidebar: collapsible-to-icon with a project switcher (header) and the CURRENT
	// zone's own routes (content, from the `zoneNav` prop each zone passes). The cross-zone list and
	// the identity/theme footer both moved to the top navbar — the sidebar is in-zone navigation only,
	// plus an OPTIONAL zone-owned `footer` snippet (e.g. media's live service-status popover).
	let {
		pathname = '',
		project,
		zoneNav = null,
		footer,
	}: {
		pathname?: string;
		project?: Project;
		zoneNav?: ZoneNavConfig | null;
		footer?: Snippet;
	} = $props();
</script>

<Sidebar.Root collapsible="icon">
	<Sidebar.Header>
		<ProjectSwitcher {project} />
	</Sidebar.Header>
	<Sidebar.Content>
		<ZoneNav {pathname} nav={zoneNav} />
	</Sidebar.Content>
	{#if footer}
		<Sidebar.Footer>{@render footer()}</Sidebar.Footer>
	{/if}
	<Sidebar.Rail />
</Sidebar.Root>
