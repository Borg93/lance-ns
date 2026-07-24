<script lang="ts">
	import '../app.css';
	import { onMount, type Snippet } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { TopNavbar } from '@rask/ui/shell';
	import { MeSchema, parse, type Me } from '@rask/api';
	import type { LayoutData } from './$types';

	let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// The estate-constant top navbar: cross-zone IA + identity, identical in every MFE. `me` comes
	// browser-side from this zone's bearer-forwarding /capi/v1/me pass-through (null = signed out /
	// unreachable → base entries only, fail-closed on the admin surfaces). The annotator's own
	// canvas shell fills the content area below.
	let me = $state<Me | null>(null);
	let meLoading = $state(true);
	onMount(async () => {
		try {
			const res = await fetch(`${base}/capi/v1/me`);
			me = res.ok ? parse(MeSchema, await res.json()) : null;
		} catch {
			me = null;
		}
		meLoading = false;
	});
</script>

<div class="flex h-svh flex-col overflow-hidden">
	<!-- The cross-zone estate navbar — the one constant across every microfrontend. -->
	<header class="border-border bg-background flex h-12 shrink-0 items-center border-b px-4">
		<TopNavbar
			pathname={page.url.pathname}
			{me}
			{meLoading}
			user={data.user}
			authEnabled={data.authEnabled}
		/>
	</header>
	<main class="min-h-0 flex-1 overflow-hidden">
		{@render children()}
	</main>
</div>
