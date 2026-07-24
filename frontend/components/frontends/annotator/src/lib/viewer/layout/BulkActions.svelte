<script lang="ts">
	// Bulk-actions bar — shown when >1 annotation is multi-selected (Shift/Ctrl-click).
	// Accept/reject/label the whole selection at once (Label Studio "apply to selection"),
	// all through the controller's picked LabelOp seam.
	import { Check, X } from 'lucide-svelte';
	import { Button } from '@lance/ui';
	import type { AnnotatorController } from '../annotator.svelte';

	let { controller }: { controller: AnnotatorController } = $props();
</script>

<div class="border-border flex flex-col gap-2 border-b p-3" data-testid="bulk-actions">
	<div class="flex items-center justify-between text-xs">
		<span class="font-medium">{controller.selectedSet.size} selected</span>
		<Button variant="ghost" size="sm" onclick={() => controller.clearSelection()}>Clear</Button>
	</div>
	<div class="flex gap-1">
		<Button
			variant="outline"
			size="sm"
			class="flex-1"
			onclick={() => controller.bulkStatus('accepted')}
		>
			<Check class="size-3.5" /> Accept all
		</Button>
		<Button
			variant="outline"
			size="sm"
			class="flex-1"
			onclick={() => controller.bulkStatus('rejected')}
		>
			<X class="size-3.5" /> Reject all
		</Button>
	</div>
	{#if controller.labelClasses.length}
		<div class="flex flex-wrap gap-1" title="Apply label to all selected">
			{#each controller.labelClasses as lc (lc)}
				<button
					class="border-border hover:bg-muted rounded border px-1.5 py-0.5 text-[11px]"
					onclick={() => controller.applyLabel(lc)}
				>
					{lc}
				</button>
			{/each}
		</div>
	{/if}
</div>
