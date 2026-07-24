<script lang="ts">
	import { getHealth, type Health } from '@lance/api';
	import { Popover } from 'bits-ui';
	import { Activity } from 'lucide-svelte';

	let health = $state<Health | null>(null);
	let lastError = $state<string | null>(null);

	async function refresh() {
		try {
			health = await getHealth();
			lastError = null;
		} catch (e) {
			lastError = e instanceof Error ? e.message : 'fetch failed';
			health = null;
		}
	}

	$effect(() => {
		refresh();
		const id = setInterval(refresh, 10_000);
		return () => clearInterval(id);
	});

	/** Overall colour: green if both up, amber if one down, red if both down or backend unreachable. */
	const tone = $derived.by(() => {
		if (!health) return 'red';
		const up = (health.embed.ok ? 1 : 0) + (health.rerank.ok ? 1 : 0);
		return up === 2 ? 'green' : up === 1 ? 'amber' : 'red';
	});

	const dotClass = (ok: boolean | undefined) =>
		ok === undefined ? 'bg-muted-foreground/40' : ok ? 'bg-emerald-500' : 'bg-red-500';
</script>

<Popover.Root>
	<Popover.Trigger
		class="hover:bg-secondary/60 flex items-center gap-1.5 rounded px-2 py-1 text-[11px]"
		title="Service status"
	>
		<span
			class="size-2 rounded-full {tone === 'green'
				? 'bg-emerald-500'
				: tone === 'amber'
					? 'bg-amber-500'
					: 'bg-red-500'}"
		></span>
		<Activity class="text-muted-foreground size-3.5" />
		<span class="text-muted-foreground hidden group-data-[collapsible=icon]:!hidden sm:inline"
			>services</span
		>
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			side="top"
			sideOffset={8}
			align="start"
			class="border-border bg-card z-50 w-80 rounded-md border p-3 text-xs shadow-md"
		>
			{#if lastError}
				<div class="text-destructive">Backend unreachable: {lastError}</div>
				<button
					type="button"
					class="border-border hover:bg-secondary mt-2 rounded border px-2 py-1"
					onclick={refresh}
				>
					retry
				</button>
			{:else if !health}
				<div class="text-muted-foreground">Loading…</div>
			{:else}
				<div class="space-y-2">
					<div>
						<div class="text-foreground mb-1 font-semibold">vLLM services</div>
						<div class="flex items-center gap-2">
							<span class="size-2 rounded-full {dotClass(health.embed.ok)}"></span>
							<span class="font-mono text-[10px]">embed</span>
							<span class="text-muted-foreground ml-auto truncate font-mono text-[10px]">
								{health.embed.url}
							</span>
						</div>
						{#if !health.embed.ok && health.embed.error}
							<div class="text-destructive mt-0.5 ml-4 text-[10px]">{health.embed.error}</div>
						{/if}
						<div class="mt-1 flex items-center gap-2">
							<span class="size-2 rounded-full {dotClass(health.rerank.ok)}"></span>
							<span class="font-mono text-[10px]">rerank</span>
							<span class="text-muted-foreground ml-auto truncate font-mono text-[10px]">
								{health.rerank.url}
							</span>
						</div>
						{#if !health.rerank.ok && health.rerank.error}
							<div class="text-destructive mt-0.5 ml-4 text-[10px]">{health.rerank.error}</div>
						{/if}
					</div>

					<div class="border-border border-t pt-2">
						<div class="text-foreground mb-1 font-semibold">Lance dataset</div>
						<div class="text-muted-foreground font-mono text-[10px] break-all">
							{health.db.path}
						</div>
						<div class="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
							<span class="text-muted-foreground">tables</span>
							<span class="text-foreground font-mono">{health.db.tables.join(', ')}</span>
							<span class="text-muted-foreground">chunks</span>
							<span class="text-foreground font-mono">{health.db.chunks.toLocaleString()}</span>
							<span class="text-muted-foreground">documents</span>
							<span class="text-foreground font-mono">{health.db.documents.toLocaleString()}</span>
						</div>
					</div>

					<button
						type="button"
						class="border-border hover:bg-secondary w-full rounded border px-2 py-1"
						onclick={refresh}
					>
						refresh
					</button>
				</div>
			{/if}
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
