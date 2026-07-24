<script lang="ts">
	import { NavigationMenu } from 'bits-ui';
	import { Skeleton } from '../components/skeleton/index.js';
	import NavbarUser from './navbar-user.svelte';
	import { cn } from '../utils/cn.js';
	import { topNav, zoneOf, type Me, type NavUser } from './nav-config.js';

	// The shared top navbar — the cross-zone IA (bits-ui NavigationMenu). One entry per microfrontend
	// zone; Admin + Access appear only for an estate admin (`me.estate_admin`, the frozen /v1/me
	// contract — fail-closed: no `me`, no admin entries). The identity/theme control (the old sidebar
	// footer nav-user) lives on the right side. Bare flex chrome on purpose: the mount decides the
	// framing (home wraps it in a bordered page header; AppShell sits it in the inset header row).
	//
	// `me` is the RESOLVED identity (null = signed out / lookup failed); `meLoading` renders skeleton
	// pills instead, so a zone streaming `fetchMe()` shows loading chrome, never a flash of the
	// non-admin entry set pretending to be the truth.
	let {
		pathname = '',
		me = null,
		meLoading = false,
		authEnabled = false,
		user = null,
		class: className,
	}: {
		pathname?: string;
		/** The frozen /v1/me identity, or null when signed out / unresolved. */
		me?: Me | null;
		/** True while the zone's fetchMe() is still in flight — renders skeletons. */
		meLoading?: boolean;
		authEnabled?: boolean;
		user?: NavUser | null;
		class?: string;
	} = $props();

	const entries = $derived(topNav(me?.estate_admin ?? false));
	// Cross-zone links leave THIS app's route manifest → hard nav (data-sveltekit-reload); the home
	// zone owns the origin root, so its zone key is ''.
	const currentZone = $derived(zoneOf(pathname));
	const crossZone = (href: string) => zoneOf(href) !== currentZone;
</script>

<nav aria-label="Zones" class={cn('flex min-w-0 flex-1 items-center gap-2', className)}>
	<NavigationMenu.Root class="min-w-0">
		<NavigationMenu.List class="flex items-center gap-0.5">
			{#if meLoading}
				{#each [0, 1, 2, 3, 4, 5] as i (i)}
					<li aria-hidden="true"><Skeleton class="h-7 w-16" /></li>
				{/each}
			{:else}
				{#each entries as entry (entry.title)}
					<NavigationMenu.Item>
						<NavigationMenu.Link
							href={entry.href}
							active={entry.match(pathname)}
							data-sveltekit-reload={crossZone(entry.href) ? '' : undefined}
							class="text-muted-foreground hover:bg-muted hover:text-foreground data-[active]:bg-muted data-[active]:text-foreground focus-visible:border-ring focus-visible:ring-ring/50 inline-flex h-7 items-center rounded-lg border border-transparent px-2.5 text-sm font-medium transition-colors outline-none focus-visible:ring-3"
						>
							{entry.title}
						</NavigationMenu.Link>
					</NavigationMenu.Item>
				{/each}
			{/if}
		</NavigationMenu.List>
	</NavigationMenu.Root>
	<div class="ml-auto flex shrink-0 items-center">
		{#if meLoading}
			<Skeleton class="size-7 rounded-full" />
		{:else}
			<NavbarUser {user} {authEnabled} {pathname} />
		{/if}
	</div>
</nav>
