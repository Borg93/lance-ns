<script lang="ts">
  // Layers section (lives inside the sidebar). Group-by column + per-group
  // visibility + color, bound to the facade's LayerStore. (Ported from ra-anno.)
  import { Eye, EyeOff, ChevronDown, ChevronRight, Layers } from 'lucide-svelte';
  import { cn } from '@lance/ui/utils';
  import type { AnnotatorController } from '../annotator.svelte';

  let { controller }: { controller: AnnotatorController } = $props();

  let collapsed = $state(false);
</script>

<section class="border-t border-border" data-testid="layer-panel">
  <button
    class="flex w-full items-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground"
    onclick={() => (collapsed = !collapsed)}
  >
    {#if collapsed}<ChevronRight class="size-3.5" />{:else}<ChevronDown class="size-3.5" />{/if}
    <Layers class="size-3.5" />
    Layers
  </button>

  {#if !collapsed}
    <div class="flex flex-col gap-2 px-3 pb-3">
      <label class="flex items-center gap-2 text-xs text-muted-foreground">
        <span class="shrink-0">Group by</span>
        <select
          class="min-w-0 flex-1 rounded border border-border bg-transparent px-1.5 py-1 text-xs text-foreground"
          value={controller.groupByColumn}
          onchange={(e) => controller.setGroupBy(e.currentTarget.value)}
        >
          {#each controller.groupColumns as c (c)}
            <option value={c}>{c}</option>
          {/each}
        </select>
      </label>

      <ul class="flex flex-col gap-0.5">
        {#each controller.groups as g (g.name)}
          <li class="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-muted/50">
            <button
              class="text-muted-foreground hover:text-foreground"
              title={controller.isHidden(g.name) ? 'Show' : 'Hide'}
              onclick={() => controller.toggleGroupVisible(g.name)}
            >
              {#if controller.isHidden(g.name)}<EyeOff class="size-3.5" />{:else}<Eye class="size-3.5" />{/if}
            </button>
            <input
              type="color"
              class="size-3.5 shrink-0 cursor-pointer rounded border-0 bg-transparent p-0"
              value={controller.groupColorHex(g.name)}
              title="Group color"
              onchange={(e) => controller.setGroupColor(g.name, e.currentTarget.value)}
            />
            <span
              class={cn('flex-1 truncate text-xs', controller.isHidden(g.name) && 'text-muted-foreground line-through')}
              title={g.name}
            >
              {g.name || '∅'}
            </span>
            <span class="text-[10px] tabular-nums text-muted-foreground">{g.count}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</section>
