<script lang="ts">
  // Interactive AI-assist bar (floating over the canvas) — two producers, one review
  // path. DETECT = GroundingDINO: type a class → boxes. SEGMENT = SAM: click or drag a
  // box → a mask. Both drop `status=prediction`, `source=model:…` rows the reviewer
  // accepts/rejects like any prediction. (ra-atr AI-labeling parity.)
  import { onDestroy } from 'svelte';
  import { MousePointerClick, Sparkles } from 'lucide-svelte';
  import { Button, Input } from '@lance/ui';
  import { cn } from '@lance/ui/utils';
  import type { AnnotatorController } from '../annotator.svelte';

  let { controller }: { controller: AnnotatorController } = $props();

  let prompt = $state('');
  let mode = $state<'detect' | 'segment'>('detect');

  function setMode(m: 'detect' | 'segment'): void {
    mode = m;
    if (m === 'segment') {
      controller.setAssistProducer('sam-click'); // route the next draw to SAM
      controller.setTool('rect'); // click or drag a box to segment
    } else {
      controller.setAssistProducer(null);
    }
  }
  function detect(): void {
    if (prompt.trim()) void controller.assist(prompt);
  }

  // Never leave the controller armed once the bar is gone (e.g. exiting edit mode).
  onDestroy(() => controller.setAssistProducer(null));
</script>

<div
  class="pointer-events-auto absolute left-1/2 top-2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-lg border border-border bg-card/90 p-1 shadow-md backdrop-blur"
  data-testid="ai-assist"
>
  <div class="flex overflow-hidden rounded border border-border">
    <Button
      variant={mode === 'detect' ? 'secondary' : 'ghost'}
      size="sm"
      aria-pressed={mode === 'detect'}
      onclick={() => setMode('detect')}
    >
      <Sparkles class="size-3.5" /> Detect
    </Button>
    <Button
      variant={mode === 'segment' ? 'secondary' : 'ghost'}
      size="sm"
      aria-pressed={mode === 'segment'}
      onclick={() => setMode('segment')}
    >
      <MousePointerClick class="size-3.5" /> Segment
    </Button>
  </div>

  {#if mode === 'detect'}
    <Input
      bind:value={prompt}
      placeholder="AI detect… (e.g. 'text line')"
      class="h-7 w-48"
      onkeydown={(e) => e.key === 'Enter' && detect()}
    />
    <Button variant="default" size="sm" disabled={!prompt.trim() || controller.saving} onclick={detect}>
      Run
    </Button>
  {:else}
    <span class={cn('px-2 text-xs text-muted-foreground', controller.saving && 'animate-pulse')}>
      {controller.saving ? 'segmenting…' : 'Click or drag a box to segment'}
    </span>
  {/if}
</div>
