<script lang="ts">
	// Saved-views control (next to the search bar): save the current query as a named view,
	// and re-apply / delete saved ones. Thin view over the savedViews store; the query
	// logic lives in $lib/saved-views. Views are scoped to the active dataset.
	import { Bookmark, Check, X } from 'lucide-svelte';
	import { activeView, type SearchSpec } from '@lance/api';
	import { savedViews } from '$lib/saved-views.svelte';
	import { Button, Input } from '@lance/ui';

	let { spec, onapply }: { spec: SearchSpec; onapply: (s: SearchSpec) => void } = $props();

	let open = $state(false);
	let name = $state('');
	const dataset = $derived(activeView().datasetParam() ?? '');
	const views = $derived(savedViews.forDataset(dataset));

	function save(): void {
		if (!name.trim()) return;
		savedViews.save(name, spec, dataset);
		name = '';
	}
	function apply(s: SearchSpec): void {
		onapply({ ...s });
		open = false;
	}
</script>

<div class="relative">
	<Button variant="outline" size="sm" onclick={() => (open = !open)} title="Saved views">
		<Bookmark class="size-3.5" />
		Views{views.length ? ` (${views.length})` : ''}
	</Button>

	{#if open}
		<div
			class="border-border bg-card absolute top-full right-0 z-20 mt-1 w-64 rounded-md border p-2 shadow-md"
		>
			<div class="flex gap-1">
				<Input
					bind:value={name}
					placeholder="Save current view as…"
					class="h-7"
					onkeydown={(e) => e.key === 'Enter' && save()}
				/>
				<Button size="sm" disabled={!name.trim()} onclick={save} title="Save view">
					<Check class="size-3.5" />
				</Button>
			</div>

			{#if views.length}
				<ul class="mt-2 flex flex-col gap-0.5">
					{#each views as v (v.name)}
						<li class="hover:bg-muted/60 flex items-center gap-1 rounded">
							<button
								class="flex-1 truncate px-2 py-1 text-left text-xs"
								title={v.spec.q || '(browse)'}
								onclick={() => apply(v.spec)}
							>
								{v.name}
							</button>
							<button
								class="text-muted-foreground hover:text-destructive px-1"
								title="Delete view"
								onclick={() => savedViews.remove(v.name, dataset)}
							>
								<X class="size-3" />
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-muted-foreground mt-2 px-1 text-[11px]">No saved views yet.</p>
			{/if}
		</div>
	{/if}
</div>
