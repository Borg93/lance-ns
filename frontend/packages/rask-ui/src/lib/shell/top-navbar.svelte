<script lang="ts">
	import { NavigationMenu } from 'bits-ui';
	import { Skeleton } from '../components/skeleton/index.js';
	import NavbarUser from './navbar-user.svelte';
	import { cn } from '../utils/cn.js';
	import { prefetchOnIntent, topNav, zoneOf, type Me, type NavUser } from './nav-config.js';

	// The shared top navbar — the cross-zone IA (bits-ui NavigationMenu). One entry per microfrontend
	// zone; Admin appears only for an estate admin (`me.estate_admin`, the frozen /v1/me contract —
	// fail-closed: no `me`, no admin entry). The identity/theme control (the old sidebar footer
	// nav-user) lives on the right side. Bare flex chrome on purpose: the mount decides the framing
	// (AppShell sits it in the inset header row).
	//
	// `me` is the RESOLVED identity (null = signed out / lookup failed); `meLoading` renders the BASE
	// entry titles as invisible text under skeleton pills instead — the same pill markup and classes
	// as the resolved links, so loading and resolved chrome have IDENTICAL dimensions (no layout
	// shift when /v1/me lands) and a zone streaming `fetchMe()` never flashes the non-admin entry set
	// pretending to be the truth.
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
	// The identity-free base set: what the skeleton reserves space for while /v1/me is in flight
	// (an admin's extra entry appends on resolve — earned content, not reserved chrome).
	const placeholders = topNav(false);
	// Cross-zone links leave THIS app's route manifest → hard nav (data-sveltekit-reload); the home
	// zone owns the origin root, so its zone key is ''.
	const currentZone = $derived(zoneOf(pathname));
	const crossZone = (href: string) => zoneOf(href) !== currentZone;

	// Warm a cross-zone target document on intent (hover/focus): rel=prefetch of the zone root —
	// see prefetchDocument for the honest browser-support scope. Same-zone links already preload
	// via data-sveltekit-preload-data. Attachment (native listeners), so bits-ui's own pointer
	// handlers on the link are never clobbered.
	const warm = (href: string) => (el: HTMLElement) =>
		crossZone(href) ? prefetchOnIntent(href)(el) : undefined;

	// One pill class list for BOTH the resolved links and the loading placeholders, so the two
	// states cannot drift apart dimensionally.
	const pill =
		'inline-flex h-7 items-center rounded-lg border border-transparent px-2.5 text-sm font-medium';
</script>

<nav aria-label="Zones" class={cn('flex min-w-0 flex-1 items-center gap-2', className)}>
	<NavigationMenu.Root class="min-w-0">
		<NavigationMenu.List class="flex items-center gap-0.5">
			{#if meLoading}
				{#each placeholders as entry (entry.title)}
					<li aria-hidden="true">
						<span class={cn(pill, 'relative')}>
							<span class="invisible">{entry.title}</span>
							<Skeleton class="absolute inset-0 rounded-lg" />
						</span>
					</li>
				{/each}
			{:else}
				{#each entries as entry (entry.title)}
					<NavigationMenu.Item>
						<NavigationMenu.Link
							href={entry.href}
							active={entry.match(pathname)}
							data-sveltekit-reload={crossZone(entry.href) ? '' : undefined}
							{@attach warm(entry.href)}
							class={cn(
								pill,
								'text-muted-foreground hover:bg-muted hover:text-foreground data-[active]:bg-muted data-[active]:text-foreground focus-visible:border-ring focus-visible:ring-ring/50 transition-colors outline-none focus-visible:ring-3',
							)}
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
			<!-- size-8 = the resolved NavbarUser trigger (Button size="icon") — same box, no shift. -->
			<Skeleton class="size-8 rounded-full" />
		{:else}
			<NavbarUser {user} {authEnabled} {pathname} />
		{/if}
	</div>
</nav>
