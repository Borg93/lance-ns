<script lang="ts">
	import '../app.css';
	import { browser } from '$app/environment';
	import { onNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import { AppShell, ForbiddenPage } from '@rask/ui/shell';
	import { onMount, type Snippet } from 'svelte';
	import type { Me } from '@rask/api';
	import { fetchMeViaBff } from '$lib/http';
	import { ADMIN_ZONE_NAV } from '$lib/nav';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// The frozen /v1/me identity, fetched browser-side through this zone's bearer-forwarding BFF.
	// In the ADMIN zone it is also the layout-level door: every route here is estate-admin only.
	let me = $state<Me | null>(null);
	let meLoading = $state(true);
	onMount(async () => {
		me = await fetchMeViaBff();
		meLoading = false;
	});

	// Fail-closed on a governed stack: content renders ONLY once /v1/me resolves with the
	// estate-admin privilege — an unresolved lookup shows the checking state, and null (signed out,
	// catalog unreachable, contract drift) is a denial, never a default-open. An auth-off stack has
	// no identities to gate on (the backend answers estate_admin=true for dev parity anyway), so it
	// stays open — same dev posture as every panel's own 401 handling.
	const forbidden = $derived(data.authEnabled && !meLoading && !(me?.estate_admin ?? false));
	// Don't advertise the zone's own routes to an identity the door refuses (or before the verdict).
	const zoneNav = $derived(forbidden || (data.authEnabled && meLoading) ? null : ADMIN_ZONE_NAV);

	// Animate soft (in-zone) navs via the View Transitions API; SSR-safe. Cross-zone
	// navs are full-document reloads (data-sveltekit-reload) and skip this.
	onNavigate((navigation) => {
		if (!document.startViewTransition) return;
		return new Promise((resolve) => {
			document.startViewTransition(async () => {
				resolve();
				await navigation.complete;
			});
		});
	});
</script>

<ModeWatcher defaultMode="dark" />
{#if browser}
	<Toaster />
{/if}

<AppShell
	pathname={page.url.pathname}
	user={data.user}
	authEnabled={data.authEnabled}
	{zoneNav}
	{me}
	{meLoading}
>
	{#if forbidden}
		<ForbiddenPage
			title="Admin is estate-admin only"
			message="This zone spans every tenant. Your identity does not hold the estate-admin privilege (can_observe_events on the FGA root)."
			home="/"
		/>
	{:else if data.authEnabled && meLoading}
		<!-- Fail-closed while the identity resolves: no admin content before the verdict. -->
		<div class="text-muted-foreground flex flex-1 items-center justify-center text-sm">
			Checking access…
		</div>
	{:else}
		<div class="min-h-0 flex-1 overflow-y-auto">
			{@render children()}
		</div>
	{/if}
</AppShell>
