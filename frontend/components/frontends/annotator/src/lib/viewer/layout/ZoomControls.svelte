<script lang="ts">
	// Floating zoom cluster (bottom-right over the canvas). Controlled by the facade.
	import { ZoomIn, ZoomOut, Maximize } from 'lucide-svelte';
	import { Button } from '@lance/ui';
	import type { AnnotatorController } from '../annotator.svelte';

	let { controller }: { controller: AnnotatorController } = $props();

	const pct = $derived(Math.round(controller.zoomPercent * 100));
</script>

<div
	class="border-border bg-card/90 pointer-events-auto absolute right-2 bottom-2 z-10 flex items-center gap-0.5 rounded-lg border p-0.5 shadow-md backdrop-blur"
	data-testid="zoom-controls"
>
	<Button variant="ghost" size="icon-xs" title="Zoom out" onclick={() => controller.zoomOut()}>
		<ZoomOut class="size-4" />
	</Button>
	<button
		class="text-muted-foreground hover:text-foreground min-w-11 rounded px-1 py-0.5 text-center text-xs tabular-nums"
		title="Reset to fit"
		onclick={() => controller.resetView()}
	>
		{pct}%
	</button>
	<Button variant="ghost" size="icon-xs" title="Zoom in" onclick={() => controller.zoomIn()}>
		<ZoomIn class="size-4" />
	</Button>
	<div class="bg-border mx-0.5 h-4 w-px"></div>
	<Button variant="ghost" size="icon-xs" title="Fit to view" onclick={() => controller.resetView()}>
		<Maximize class="size-4" />
	</Button>
</div>
