<script lang="ts">
	import '../app.css';
	import { onMount, type Snippet } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/state';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import { TopNavbar } from '@repo/ui/shell';
	import type { Me } from '@repo/api';
	import { fetchMeViaBff } from '$lib/http';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// The estate-constant top navbar: cross-zone IA + identity, identical in every MFE. `me` comes
	// browser-side from this zone's bearer-forwarding /capi/v1/me pass-through (null = signed out /
	// unreachable → base entries only, fail-closed on the admin surfaces). The annotator's own
	// canvas shell fills the content area below.
	let me = $state<Me | null>(null);
	let meLoading = $state(true);
	onMount(async () => {
		me = await fetchMeViaBff();
		meLoading = false;
	});
</script>

<!-- The estate-shared mode-watcher owns the `.dark` class, mounted exactly as every other zone
     mounts it. That is the whole point: the theme choice lives in ONE origin-wide localStorage
     key, so the navbar's toggle works here and a light estate stays light when you hop into the
     annotator. Previously this zone pinned `class="dark"` on <html> and read its own
     `lance-media-theme` key, which is why it rendered dark against a light estate. First paint
     is handled by the boot script in app.html (this zone's canvas route is ssr=false, so the
     mode-watcher head script other zones rely on never reaches the document). -->
<ModeWatcher defaultMode="dark" />
{#if browser}
	<Toaster />
{/if}

<div class="flex h-svh flex-col overflow-hidden">
	<!-- The cross-zone estate navbar — the one constant across every microfrontend. -->
	<header class="border-border bg-background flex h-12 shrink-0 items-center border-b px-4">
		<!-- `min-w-0 flex-1` is not decoration: it is the same class AppShell passes at
		     app-shell.svelte:109, and it is what makes the navbar span the row so its identity/theme
		     cluster sits on the RIGHT. Without it TopNavbar shrinks to content width and the account
		     avatar sits immediately after the last zone link — which is why this zone's login icon
		     appeared pushed to the left while media and lakehouse looked correct. Hand-rolling the
		     header instead of reusing AppShell is what let the two drift; see the follow-up task to
		     give AppShell a canvas mode so this zone can use it. -->
		<TopNavbar
			pathname={page.url.pathname}
			{me}
			{meLoading}
			user={data.user}
			authEnabled={data.authEnabled}
			class="min-w-0 flex-1"
		/>
	</header>
	<main class="min-h-0 flex-1 overflow-hidden">
		{@render children()}
	</main>
</div>
