<script lang="ts">
  // Floating zoom cluster (bottom-right over the canvas). Controlled by the facade.
  import { ZoomIn, ZoomOut, Maximize } from 'lucide-svelte';
  import { Button } from '@lance/ui';
  import type { AnnotatorController } from '../annotator.svelte';

  let { controller }: { controller: AnnotatorController } = $props();

  const pct = $derived(Math.round(controller.zoomPercent * 100));
</script>

<div
  class="pointer-events-auto absolute bottom-2 right-2 z-10 flex items-center gap-0.5 rounded-lg border border-border bg-card/90 p-0.5 shadow-md backdrop-blur"
  data-testid="zoom-controls"
>
  <Button variant="ghost" size="icon-xs" title="Zoom out" onclick={() => controller.zoomOut()}>
    <ZoomOut class="size-4" />
  </Button>
  <button
    class="min-w-11 rounded px-1 py-0.5 text-center text-xs tabular-nums text-muted-foreground hover:text-foreground"
    title="Reset to fit"
    onclick={() => controller.resetView()}
  >
    {pct}%
  </button>
  <Button variant="ghost" size="icon-xs" title="Zoom in" onclick={() => controller.zoomIn()}>
    <ZoomIn class="size-4" />
  </Button>
  <div class="mx-0.5 h-4 w-px bg-border"></div>
  <Button variant="ghost" size="icon-xs" title="Fit to view" onclick={() => controller.resetView()}>
    <Maximize class="size-4" />
  </Button>
</div>
