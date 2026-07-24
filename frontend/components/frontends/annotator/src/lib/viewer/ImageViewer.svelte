<script lang="ts">
	// Image/document viewer — the ra-anno PixiJS engine over a page image. WORKING.
	import { loadAnnotations } from '@lance/labeling/annotations-client';
	import type { PixiContext } from '@lance/engine';
	import PixiCanvas from './PixiCanvas.svelte';
	import type { ViewerProps } from './types';

	let { unit, onload, controller }: ViewerProps = $props();

	async function onready(ctx: PixiContext): Promise<void> {
		if (unit.imageUrl) await ctx.plugins.image.load(unit.imageUrl);
		// Hand the loaded still to the interaction layer so the OpenCV tools
		// (magnetic corner-snap) can lazily build its corner maps when activated.
		ctx.plugins.interaction.setImageSource(ctx.plugins.image.imageElement);
		const { table, version } = await loadAnnotations(unit.annotationsUrl);
		ctx.plugins.arrow.load(table);
		ctx.plugins.arrow.sync();
		// Lift the engine + data to the route-level facade so the annotator layout
		// (toolbar/sidebar/zoom/layers) can bind to it. No-op when unwired. The
		// annotations URL doubles as the Save (POST) target; the version drives the
		// optimistic-concurrency handshake.
		controller?.attach(ctx, table, unit.annotationsUrl, version);
		onload?.(table.numRows);
	}
</script>

<PixiCanvas {onready} />
