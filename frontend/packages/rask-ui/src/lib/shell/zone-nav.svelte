<script lang="ts">
	import * as Sidebar from '../components/sidebar/index.js';
	import type { ZoneNav } from './nav-config.js';

	// The CURRENT zone's own routes — a flat group under the zone's name. The cross-zone list moved to
	// the top navbar (`TopNavbar`), so every leaf here is same-zone by construction and stays a SOFT
	// nav (no data-sveltekit-reload — it would defeat the SPA router inside the zone). `pathname`
	// drives the active leaf via the shared norm/exact/seg matchers each zone builds its config with.
	let { pathname = '', nav = null }: { pathname?: string; nav?: ZoneNav | null } = $props();
</script>

{#if nav}
	<Sidebar.Group>
		<Sidebar.GroupLabel>{nav.title}</Sidebar.GroupLabel>
		<Sidebar.Menu>
			{#each nav.leaves as leaf (leaf.title)}
				<Sidebar.MenuItem>
					<Sidebar.MenuButton tooltipContent={leaf.title} isActive={leaf.match(pathname)}>
						{#snippet child({ props })}
							<a href={leaf.href} {...props}>
								{#if leaf.icon}
									<leaf.icon />
								{/if}
								<span>{leaf.title}</span>
							</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			{/each}
		</Sidebar.Menu>
	</Sidebar.Group>
{/if}
