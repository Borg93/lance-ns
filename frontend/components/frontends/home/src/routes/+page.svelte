<script lang="ts">
	import { Button } from '@rask/ui/button';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const zones = [
		{ title: 'Data', href: '/data', blurb: 'tables · namespaces · warehouses' },
		{ title: 'Lineage', href: '/lineage', blurb: 'graph · runs · events · columns' },
		{ title: 'Models', href: '/models', blurb: 'registry · experiments · pipeline' },
		{ title: 'Admin', href: '/admin', blurb: 'audit · dlq · access · maintenance' },
	];
</script>

<svelte:head><title>lance</title></svelte:head>

<div class="bg-background text-foreground min-h-svh px-6 py-16">
	<div class="mx-auto max-w-3xl space-y-8">
		<header class="flex items-start justify-between gap-4">
			<div class="space-y-2">
				<h1 class="text-3xl font-semibold">lance</h1>
				<p class="text-muted-foreground">Governed Lance lakehouse — pick a zone.</p>
			</div>
			{#if data.authEnabled}
				<!-- The auth control mirrors every zone's nav-user: same origin-relative /auth/* the home zone owns. -->
				<div class="flex shrink-0 items-center gap-3 text-sm">
					{#if data.user}
						<span class="text-muted-foreground">Signed in as {data.user.name}</span>
						<a class="text-foreground underline-offset-4 hover:underline" href="/auth/logout"
							>Sign out</a
						>
					{:else}
						<Button href="/auth/login?redirect=/">Sign in</Button>
					{/if}
				</div>
			{/if}
		</header>
		<div class="grid gap-4 sm:grid-cols-2">
			{#each zones as zone (zone.href)}
				<a
					href={zone.href}
					data-sveltekit-reload
					class="border-border hover:bg-accent block rounded-lg border p-5 transition-colors"
				>
					<div class="text-lg font-medium">{zone.title}</div>
					<div class="text-muted-foreground text-sm">{zone.blurb}</div>
				</a>
			{/each}
		</div>
		<Button href="/data">Open the data plane →</Button>
	</div>
</div>
