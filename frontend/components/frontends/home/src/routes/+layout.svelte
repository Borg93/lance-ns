<script lang="ts">
	import '../app.css';
	import { browser } from '$app/environment';
	import { page } from '$app/state';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import { TopNavbar } from '@rask/ui/shell';
	import type { Snippet } from 'svelte';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();
</script>

<ModeWatcher defaultMode="dark" />
{#if browser}
	<Toaster />
{/if}

<div class="bg-background text-foreground flex min-h-svh flex-col">
	<!-- The cross-zone TopNavbar mounts here first (the home zone has no sidebar shell). `me` is
	     STREAMED from the layout load: skeleton entries until it resolves, then the entry set the
	     identity earns (Admin + Access only for an estate admin). -->
	<header class="border-border bg-background/95 sticky top-0 z-10 border-b backdrop-blur">
		<div class="mx-auto flex h-14 w-full max-w-5xl items-center px-4">
			{#await data.streamed.me}
				<TopNavbar
					pathname={page.url.pathname}
					meLoading
					user={data.user}
					authEnabled={data.authEnabled}
				/>
			{:then me}
				<TopNavbar
					pathname={page.url.pathname}
					{me}
					user={data.user}
					authEnabled={data.authEnabled}
				/>
			{/await}
		</div>
	</header>
	<main class="flex flex-1 flex-col">{@render children()}</main>
</div>
