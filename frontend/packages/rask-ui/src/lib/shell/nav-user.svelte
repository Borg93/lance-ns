<script lang="ts">
	import { Avatar, AvatarFallback } from '../components/avatar/index.js';
	import * as DropdownMenu from '../components/dropdown-menu/index.js';
	import * as Sidebar from '../components/sidebar/index.js';
	import { useSidebar } from '../components/sidebar/index.js';
	import { toggleMode } from 'mode-watcher';
	import { ChevronsUpDown, Sun, Moon, Settings, LogIn, LogOut } from '@lucide/svelte';
	import type { NavUser } from './nav-config.js';

	// sidebar-07 NavUser, adapted: identity + theme toggle + settings + the shared auth control.
	// App-specific live status (e.g. Ray health) lives in the app's own pages, not here — the shared
	// shell never imports app data like @rask/api; the identity flows in as a plain prop from each
	// zone's +layout.server.ts (single-sourced via @rask/api's sessionToUser).
	//
	// `authEnabled` drives the auth affordance (identical in every MFE): off → today's local identity,
	// no auth UI; on + signed in → identity + Sign out; on + signed out (user null) → a "Sign in" prompt.
	// Login/logout are ORIGIN-relative links that HARD-navigate (data-sveltekit-reload) to the home zone,
	// which owns /auth/*; the session cookie is set at path "/" so it's shared across every path-routed zone.
	let {
		user = null,
		authEnabled = false,
		pathname = '',
	}: { user?: NavUser | null; authEnabled?: boolean; pathname?: string } = $props();
	const sidebar = useSidebar();

	const signedIn = $derived(!!user);
	// The identity shown on the trigger: the real user, the auth-off local placeholder, or a "Sign in" cue.
	const identity = $derived(
		user ??
			(authEnabled
				? { name: 'Sign in', email: 'not signed in', initials: '?' }
				: { name: 'rask', email: 'local', initials: 'RA' }),
	);
	// Return to the zone the user signed in from (validated as a local path in the login route).
	const loginHref = $derived(`/auth/login?redirect=${encodeURIComponent(pathname || '/')}`);
</script>

<Sidebar.Menu>
	<Sidebar.MenuItem>
		<DropdownMenu.Root>
			<DropdownMenu.Trigger>
				{#snippet child({ props })}
					<Sidebar.MenuButton
						{...props}
						size="lg"
						class="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
					>
						<Avatar class="size-8 rounded-lg">
							<AvatarFallback class="rounded-lg">{identity.initials ?? 'RA'}</AvatarFallback>
						</Avatar>
						<div class="grid flex-1 text-left text-sm leading-tight">
							<span class="truncate font-medium">{identity.name}</span>
							<span class="truncate text-xs">{identity.email ?? 'local'}</span>
						</div>
						<ChevronsUpDown class="ml-auto size-4" />
					</Sidebar.MenuButton>
				{/snippet}
			</DropdownMenu.Trigger>
			<DropdownMenu.Content
				class="w-(--bits-dropdown-menu-anchor-width) min-w-56 rounded-lg"
				side={sidebar.isMobile ? 'bottom' : 'right'}
				align="end"
				sideOffset={4}
			>
				<DropdownMenu.Label class="p-0 font-normal">
					<div class="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
						<Avatar class="size-8 rounded-lg">
							<AvatarFallback class="rounded-lg">{identity.initials ?? 'RA'}</AvatarFallback>
						</Avatar>
						<div class="grid flex-1 text-left text-sm leading-tight">
							<span class="truncate font-medium">{identity.name}</span>
							<span class="truncate text-xs">{identity.email ?? 'local'}</span>
						</div>
					</div>
				</DropdownMenu.Label>
				<DropdownMenu.Separator />
				<DropdownMenu.Item onclick={toggleMode}>
					<Sun class="size-4 dark:hidden" />
					<Moon class="hidden size-4 dark:block" />
					Toggle theme
				</DropdownMenu.Item>
				<DropdownMenu.Item disabled>
					<Settings class="size-4" />
					Settings (soon)
				</DropdownMenu.Item>
				{#if authEnabled}
					<DropdownMenu.Separator />
					{#if signedIn}
						<!-- Cross-zone hard-nav to the home zone's /auth/logout; clears the origin-wide session cookie.
						     The shadcn Item wrapper omits bits-ui's `child`, so the anchor is the item's content and
						     fills the row (data-sveltekit-reload leaves this zone's route manifest). -->
						<DropdownMenu.Item>
							<a href="/auth/logout" data-sveltekit-reload class="flex w-full items-center gap-2">
								<LogOut class="size-4" />
								Sign out
							</a>
						</DropdownMenu.Item>
					{:else}
						<!-- Cross-zone hard-nav to the home zone's /auth/login; returns here after the round-trip. -->
						<DropdownMenu.Item>
							<a href={loginHref} data-sveltekit-reload class="flex w-full items-center gap-2">
								<LogIn class="size-4" />
								Sign in
							</a>
						</DropdownMenu.Item>
					{/if}
				{/if}
			</DropdownMenu.Content>
		</DropdownMenu.Root>
	</Sidebar.MenuItem>
</Sidebar.Menu>
