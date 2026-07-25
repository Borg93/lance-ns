<script lang="ts">
	// The zone sidebar's footer control: a live service/dataset health popover.
	// Styled on the estate design system (button variants + the success/warning/
	// destructive status tokens) so it reads as part of the shared sidebar rather
	// than a zone-private widget.
	import { getHealth, type Health } from '@repo/media-api';
	import { Popover } from 'bits-ui';
	import { Activity } from '@lucide/svelte';
	import { Button, buttonVariants, cn } from '@repo/ui';

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

	/** Overall dot: success when both are up, warning when one is down, destructive
	 *  when both are down or the backend is unreachable — the estate status tokens. */
	const tone = $derived.by(() => {
		if (!health) return 'bg-destructive';
		const up = (health.embed.ok ? 1 : 0) + (health.rerank.ok ? 1 : 0);
		return up === 2 ? 'bg-success' : up === 1 ? 'bg-warning' : 'bg-destructive';
	});

	const dotClass = (ok: boolean | undefined) =>
		ok === undefined ? 'bg-muted-foreground/40' : ok ? 'bg-success' : 'bg-destructive';
</script>

<Popover.Root>
	<Popover.Trigger
		class={cn(
	buttonVariants({ variant: 'ghost', size: 'sm' }),
	'text-muted-foreground w-full justify-start',
)}
		title="Service status"
	>
		<span class="size-2 rounded-full {tone}"></span>
		<Activity />
		<span class="group-data-[collapsible=icon]:!hidden">services</span>
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			side="top"
			sideOffset={8}
			align="start"
			class="border-border bg-popover text-popover-foreground z-50 w-80 rounded-lg border p-3 text-xs shadow-md"
		>
			{#if lastError}
				<div class="text-destructive">Backend unreachable: {lastError}</div>
				<Button variant="outline" size="xs" class="mt-2" onclick={refresh}>Retry</Button>
			{:else if !health}
				<div class="text-muted-foreground">Loading…</div>
			{:else}
				<div class="flex flex-col gap-2">
					<div>
						<div class="text-foreground mb-1 font-semibold">vLLM services</div>
						<div class="flex items-center gap-2">
							<span class="size-2 rounded-full {dotClass(health.embed.ok)}"></span>
							<span class="font-mono text-[0.7rem]">embed</span>
							<span class="text-muted-foreground ml-auto truncate font-mono text-[0.7rem]">
								{health.embed.url}
							</span>
						</div>
						{#if !health.embed.ok && health.embed.error}
							<div class="text-destructive mt-0.5 ml-4 text-[0.7rem]">{health.embed.error}</div>
						{/if}
						<div class="mt-1 flex items-center gap-2">
							<span class="size-2 rounded-full {dotClass(health.rerank.ok)}"></span>
							<span class="font-mono text-[0.7rem]">rerank</span>
							<span class="text-muted-foreground ml-auto truncate font-mono text-[0.7rem]">
								{health.rerank.url}
							</span>
						</div>
						{#if !health.rerank.ok && health.rerank.error}
							<div class="text-destructive mt-0.5 ml-4 text-[0.7rem]">{health.rerank.error}</div>
						{/if}
					</div>

					<div class="border-border border-t pt-2">
						<div class="text-foreground mb-1 font-semibold">Lance dataset</div>
						<div class="text-muted-foreground font-mono text-[0.7rem] break-all">
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

					<Button variant="outline" size="sm" class="w-full" onclick={refresh}>Refresh</Button>
				</div>
			{/if}
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
