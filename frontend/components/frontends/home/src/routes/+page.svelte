<script lang="ts">
	import { Button } from '@rask/ui/button';

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
		<header class="space-y-2">
			<h1 class="text-3xl font-semibold">lance</h1>
			<p class="text-muted-foreground">Governed Lance lakehouse — pick a zone.</p>
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
