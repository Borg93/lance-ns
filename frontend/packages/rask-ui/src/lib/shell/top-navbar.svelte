<script lang="ts">
	import * as NavigationMenu from '../components/navigation-menu/index.js';
	import { navigationMenuTriggerStyle } from '../components/navigation-menu/index.js';
	import { Skeleton } from '../components/skeleton/index.js';
	import NavbarUser from './navbar-user.svelte';
	import { cn } from '../utils/cn.js';
	import { ChevronDown } from '@lucide/svelte';
	import {
		norm,
		prefetchOnIntent,
		topNav,
		under,
		zoneOf,
		type Me,
		type NavUser,
		type TopNavEntry,
		type TopNavItem,
	} from './nav-config.js';

	// The shared top navbar — the cross-zone IA on the shadcn-svelte NavigationMenu shape. One entry
	// per microfrontend zone; a zone that carries `items` renders as a trigger opening a panel of its
	// sub-areas (so the estate is one hop away from anywhere), and a zone with a single surface stays
	// a plain link. Admin appears only for an estate admin (`me.estate_admin`, the frozen /v1/me
	// contract — fail-closed: no `me`, no admin entry); Access is never a top-level entry, it is one
	// row of Admin's panel. The identity/theme control (the old sidebar footer nav-user) lives on the
	// right side. Bare flex chrome on purpose: the mount decides the framing (AppShell sits it on the
	// header's navbar row).
	//
	// `me` is the RESOLVED identity (null = signed out / lookup failed); `meLoading` renders the BASE
	// entry titles as invisible text under skeleton pills instead — the same chrome classes and the
	// same chevron reservation as the resolved entries, so loading and resolved states have IDENTICAL
	// dimensions (no layout shift when /v1/me lands) and a zone streaming `fetchMe()` never flashes
	// the non-admin entry set pretending to be the truth.
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
	// zone owns the origin root, so its zone key is ''. A plain function over the `pathname` prop, not
	// a `$derived`: the panel rows render inside bits-ui's portalled Content, and a derived read from
	// there warns (`derived_inert`) as the panel tears down.
	const crossZone = (href: string) => zoneOf(href) !== zoneOf(pathname);

	// Warm a cross-zone target document on intent (hover/focus): rel=prefetch of the zone root —
	// see prefetchDocument for the honest browser-support scope. Same-zone links already preload
	// via data-sveltekit-preload-data. Attachment (native listeners), so bits-ui's own pointer
	// handlers on the link are never clobbered.
	const warm = (href: string) => (el: HTMLElement) =>
		crossZone(href) ? prefetchOnIntent(href)(el) : undefined;

	// A panel row is lit when the current path is under it — except a row that IS the zone root
	// (Lineage's Graph, Media's Search), which matches exactly or it would light up on every sibling.
	const itemActive = (entry: TopNavEntry, item: TopNavItem) =>
		item.href === entry.href ? norm(pathname) === item.href : under(item.href)(pathname);

	// One chrome class list for the resolved entries AND the loading placeholders, so the two states
	// cannot drift apart dimensionally — and shared with the plain links, so a link and a trigger are
	// the same box.
	const chrome = navigationMenuTriggerStyle();
</script>

<div class={cn('flex min-w-0 items-center gap-2', className)}>
	<!-- `aria-label` overrides the primitive's default "main", so this IS the zones landmark — one
	     nav element, not a nav nested inside a nav. -->
	<NavigationMenu.Root aria-label="Zones" class="min-w-0">
		<NavigationMenu.List class="justify-start gap-0.5">
			{#if meLoading}
				{#each placeholders as entry (entry.title)}
					<li aria-hidden="true">
						<span class={cn(chrome, 'relative')}>
							<span class="invisible">{entry.title}</span>
							{#if entry.items || entry.groups}
								<!-- Reserve the trigger's chevron too, or an entry with a panel would grow by
								     its width the moment the identity lands. -->
								<ChevronDown class="invisible size-3" />
							{/if}
							<Skeleton class="absolute inset-0 rounded-lg" />
						</span>
					</li>
				{/each}
			{:else}
				{#each entries as entry (entry.title)}
					<NavigationMenu.Item>
						{#if entry.groups}
							<!-- A trigger spanning SEVERAL concerns (Lakehouse: the catalog, the model
							     registry and — for an estate admin — governance/operations over the same
							     estate) renders labelled columns, so the panel explains the shape instead
							     of listing a dozen undifferentiated rows. Column count follows the groups
							     the viewer actually gets, so a non-admin sees a tighter two-column panel. -->
							<NavigationMenu.Trigger data-active={entry.match(pathname) ? '' : undefined}>
								{entry.title}
							</NavigationMenu.Trigger>
							<NavigationMenu.Content>
								<div
									class="grid gap-x-3 gap-y-1 p-2 md:w-[46rem]"
									style="grid-template-columns: repeat({entry.groups.length}, minmax(0, 1fr))"
								>
									{#each entry.groups as group (group.label)}
										<div>
											<p
												class="text-muted-foreground px-3 pt-1 pb-1.5 text-[0.6875rem] font-semibold tracking-wide uppercase"
											>
												{group.label}
											</p>
											<ul class="grid gap-1">
												{#each group.items as item (item.href)}
													<li>
														<NavigationMenu.Link
															href={item.href}
															active={itemActive(entry, item)}
															data-sveltekit-reload={crossZone(item.href) ? '' : undefined}
															{@attach warm(item.href)}
														>
															<span class="text-sm leading-none font-medium">{item.title}</span>
															<span class="text-muted-foreground line-clamp-2 text-xs leading-snug">
																{item.description}
															</span>
														</NavigationMenu.Link>
													</li>
												{/each}
											</ul>
										</div>
									{/each}
								</div>
							</NavigationMenu.Content>
						{:else if entry.items}
							<NavigationMenu.Trigger data-active={entry.match(pathname) ? '' : undefined}>
								{entry.title}
							</NavigationMenu.Trigger>
							<NavigationMenu.Content>
								<ul class="grid gap-1 p-2 md:w-[30rem] md:grid-cols-2">
									{#if !entry.items.some((i) => i.href === entry.href)}
										<!-- The zone root itself — a panel must not be the only way in, and the
										     trigger is a button, not a link. Skipped when a row already IS the
										     root (lineage's Graph, media's Search), so no href appears twice. -->
										<li class="md:col-span-2">
											<NavigationMenu.Link
												href={entry.href}
												active={norm(pathname) === entry.href}
												data-sveltekit-reload={crossZone(entry.href) ? '' : undefined}
												{@attach warm(entry.href)}
												class="bg-muted/40 p-3"
											>
												<span class="text-foreground text-sm leading-none font-medium"
													>{entry.title}</span
												>
												<span class="text-muted-foreground text-xs leading-snug">
													Open the {entry.title.toLowerCase()} zone.
												</span>
											</NavigationMenu.Link>
										</li>
									{/if}
									{#each entry.items as item (item.href)}
										<li>
											<NavigationMenu.Link
												href={item.href}
												active={itemActive(entry, item)}
												data-sveltekit-reload={crossZone(item.href) ? '' : undefined}
												{@attach warm(item.href)}
											>
												<span class="text-sm leading-none font-medium">{item.title}</span>
												<span class="text-muted-foreground line-clamp-2 text-xs leading-snug">
													{item.description}
												</span>
											</NavigationMenu.Link>
										</li>
									{/each}
								</ul>
							</NavigationMenu.Content>
						{:else}
							<NavigationMenu.Link
								href={entry.href}
								active={entry.match(pathname)}
								data-sveltekit-reload={crossZone(entry.href) ? '' : undefined}
								{@attach warm(entry.href)}
								class={chrome}
							>
								{entry.title}
							</NavigationMenu.Link>
						{/if}
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
</div>
