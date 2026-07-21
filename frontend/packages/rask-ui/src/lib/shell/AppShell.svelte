<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Zone {
		title: string;
		href: string;
	}

	// The 4 lance micro-frontend zones. Cross-zone links are FULL-DOCUMENT navigations
	// (data-sveltekit-reload): each zone is a SEPARATE SvelteKit app that doesn't own the
	// other zones' routes, so a soft client-router nav would 404. P1 replaces this with the
	// adopted rask nav-config (collapsible domains + active-match + nav-user from the session).
	const ZONES: Zone[] = [
		{ title: 'Data', href: '/data' },
		{ title: 'Lineage', href: '/lineage' },
		{ title: 'Models', href: '/models' },
		{ title: 'Admin', href: '/admin' },
	];

	let { pathname, children }: { pathname: string; children: Snippet } = $props();

	const isActive = (href: string): boolean => pathname === href || pathname.startsWith(href + '/');
</script>

<div class="bg-background text-foreground flex min-h-svh">
	<aside
		class="bg-sidebar text-sidebar-foreground border-sidebar-border w-56 shrink-0 border-r p-4"
	>
		<a href="/" data-sveltekit-reload class="mb-6 block text-lg font-semibold">lance</a>
		<nav class="flex flex-col gap-1">
			{#each ZONES as zone (zone.href)}
				<a
					href={zone.href}
					data-sveltekit-reload
					class="hover:bg-sidebar-accent rounded-md px-3 py-2 text-sm {isActive(zone.href)
						? 'bg-sidebar-accent font-medium'
						: ''}"
				>
					{zone.title}
				</a>
			{/each}
		</nav>
	</aside>
	<main class="flex-1 p-6">
		{@render children()}
	</main>
</div>
