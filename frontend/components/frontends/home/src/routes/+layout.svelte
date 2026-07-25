<script lang="ts">
	import '../app.css';
	import { browser } from '$app/environment';
	import { page } from '$app/state';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import { AppShell } from '@repo/ui/shell';
	import type { Snippet } from 'svelte';
	import { HOME_ZONE_NAV } from '$lib/nav';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();
</script>

<ModeWatcher defaultMode="dark" />
{#if browser}
	<Toaster />
{/if}

<!-- The same estate shell as every other zone (identical server-rendered chrome, so a cross-zone
     hop into "/" paints stable navbar + sidebar immediately). `me` resolved in the layout load —
     the navbar SSRs its final entry set, no skeleton pass on the landing. -->
<AppShell
	pathname={page.url.pathname}
	user={data.user}
	authEnabled={data.authEnabled}
	zoneNav={HOME_ZONE_NAV}
	me={data.me}
	meLoading={false}
>
	<div class="min-h-0 flex-1 overflow-y-auto">
		{@render children()}
	</div>
</AppShell>
