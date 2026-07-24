<script lang="ts">
  // Left tool rail — the primary command surface. Fully controlled: reads/writes
  // the AnnotatorController facade, never the engine directly. (Ported from
  // ra-anno Toolbar.svelte, trimmed to functional controls for our engine.)
  import { Eye, Pencil, Trash2, Spline, Eraser, Undo2, Redo2, Save } from 'lucide-svelte';
  import { Button } from '@lance/ui';
  import { cn } from '@lance/ui/utils';
  import { TOOL_DEFS } from '../tool-defs';
  import type { AnnotatorController } from '../annotator.svelte';

  // `spatial` = this unit has a canvas to draw ON (image / video frame). Audio has no
  // spatial lane — its segments are made by dragging on the waveform — so the draw
  // tools + pan + convert-to-polygon are hidden; mode/undo/redo/save/delete stay.
  let { controller, spatial = true }: { controller: AnnotatorController; spatial?: boolean } =
    $props();

  const visible = $derived(
    spatial
      ? TOOL_DEFS.filter((t) => (!t.drawing || controller.canDraw) && (!t.cv || controller.cvCapable))
      : [],
  );
</script>

<div
  class="flex h-full w-11 shrink-0 flex-col items-center gap-1 border-r border-border bg-card py-2"
  data-testid="annotator-toolbar"
>
  <!-- Mode toggle -->
  <Button
    variant={controller.mode === 'edit' ? 'default' : 'ghost'}
    size="icon-sm"
    title={controller.mode === 'edit' ? 'Edit mode (click to view)' : 'View mode (click to edit)'}
    aria-pressed={controller.mode === 'edit'}
    onclick={() => controller.toggleMode()}
  >
    {#if controller.mode === 'edit'}<Pencil class="size-4" />{:else}<Eye class="size-4" />{/if}
  </Button>

  {#if spatial}
    <div class="my-1 h-px w-6 bg-border"></div>

    {#each visible as t (t.tool)}
      {@const Icon = t.icon}
      {@const cvLoading = t.cv === true && controller.activeTool === t.tool && !controller.cvReady.has(t.tool)}
      <Button
        variant={controller.activeTool === t.tool ? 'default' : 'ghost'}
        size="icon-sm"
        title={`${t.label} (${t.key})${cvLoading ? ' — loading OpenCV…' : ''}`}
        aria-pressed={controller.activeTool === t.tool}
        data-cvready={t.cv ? controller.cvReady.has(t.tool) : undefined}
        data-snapped={t.tool === 'magnetic' ? controller.magneticSnapped : undefined}
        onclick={() => controller.setTool(t.tool)}
      >
        <Icon class={cn('size-4', cvLoading && 'animate-pulse')} />
      </Button>
    {/each}

    {#if controller.activeTool === 'brush'}
      <Button
        variant={controller.brushOptions.erasing ? 'default' : 'ghost'}
        size="icon-sm"
        title="Erase (brush)"
        aria-pressed={controller.brushOptions.erasing}
        onclick={() => controller.setBrushOptions({ erasing: !controller.brushOptions.erasing })}
      >
        <Eraser class="size-4" />
      </Button>
    {/if}
  {/if}

  <div class="my-1 h-px w-6 bg-border"></div>

  <!-- Undo / redo (field edits: relabel / accept / reject / text) -->
  <Button
    variant="ghost"
    size="icon-sm"
    title="Undo (Ctrl+Z)"
    disabled={!controller.canUndo}
    onclick={() => controller.undo()}
  >
    <Undo2 class="size-4" />
  </Button>
  <Button
    variant="ghost"
    size="icon-sm"
    title="Redo (Ctrl+Shift+Z)"
    disabled={!controller.canRedo}
    onclick={() => controller.redo()}
  >
    <Redo2 class="size-4" />
  </Button>
  <Button
    variant={controller.canSave ? 'default' : 'ghost'}
    size="icon-sm"
    title={controller.saveError ?? (controller.dirty ? 'Save to Lance (Ctrl+S)' : 'No unsaved edits')}
    disabled={!controller.canSave}
    onclick={() => controller.save()}
  >
    <Save class={cn('size-4', controller.saving && 'animate-pulse', controller.saveError && 'text-destructive')} />
  </Button>

  <div class="my-1 h-px w-6 bg-border"></div>

  <!-- Selection actions -->
  {#if spatial}
    <Button
      variant="ghost"
      size="icon-sm"
      title="Convert to polygon (P)"
      disabled={controller.selectedIndex == null}
      onclick={() => controller.convertToPolygon()}
    >
      <Spline class="size-4" />
    </Button>
  {/if}
  <Button
    variant="ghost"
    size="icon-sm"
    title="Delete selected (Del)"
    disabled={controller.selectedIndex == null}
    onclick={() => controller.deleteSelected()}
  >
    <Trash2 class="size-4" />
  </Button>

  <div class="mt-auto flex flex-col items-center gap-1">
    <span
      class={cn(
        'size-2 rounded-full',
        controller.dirty ? 'bg-amber-500' : 'bg-transparent',
      )}
      title={controller.dirty ? 'Unsaved edits' : 'No pending edits'}
    ></span>
    <span class="text-[10px] tabular-nums text-muted-foreground" title="Annotation count">
      {controller.count}
    </span>
  </div>
</div>
