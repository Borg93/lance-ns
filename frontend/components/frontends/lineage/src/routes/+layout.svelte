<script lang="ts">
	import '../app.css';
	import { browser } from '$app/environment';
	import { onNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import { AppShell } from '@rask/ui/shell';
	import { onMount, type Snippet } from 'svelte';
	import { fetchMeViaBff, type Me } from '$lib/me';
	import { LINEAGE_ZONE_NAV } from '$lib/nav';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// The frozen /v1/me identity for the navbar, fetched browser-side through this zone's
	// bearer-forwarding BFF (skeleton pills while in flight; null = signed out / unreachable →
	// base entries only, fail-closed on the admin surfaces).
	let me = $state<Me | null>(null);
	let meLoading = $state(true);
	onMount(async () => {
		me = await fetchMeViaBff();
		meLoading = false;
	});

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
	zoneNav={LINEAGE_ZONE_NAV}
	{me}
	{meLoading}
>
	<!-- The wrapper scrolls the list/detail pages; the Graph + Columns canvases set height:100%
	     inside it (the wrapper is a sized flex item, so they fill it and never scroll). -->
	<div class="zone-scroll">
		{@render children()}
	</div>
</AppShell>

<style>
	.zone-scroll {
		display: flex;
		flex-direction: column;
		flex: 1 1 0;
		min-height: 0;
		overflow-y: auto;
	}
</style>
