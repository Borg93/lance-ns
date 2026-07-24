<script lang="ts">
  /**
   * AtlasLegend — presentational legend / distribution panel for AtlasMap.
   *
   * Renders the two-branch legend (cluster vs categorical colour mode) with its
   * clickable rows + distribution bars. Pure props-in / callbacks-out: it does
   * NO data computation and never touches the cross-filter store directly —
   * AtlasMap computes the rows (via ./atlas-legend) and threads the click/toggle
   * handlers through, so the component stays dumb + testable.
   */
  import { Eye, EyeOff } from 'lucide-svelte';
  import type { ClusterLegendRow, CategoryLegendRow } from './atlas-legend';
  import type { ColorBy } from './cross-filter.svelte';

  let {
    legendMode,
    clusterRows,
    categoryRows,
    clusterStats,
    categoryTitle,
    categoryTotal,
    legendFiltered,
    hidden,
    isDark,
    onPickCluster,
    onPickCategory,
    onToggleHidden,
    onShowAll,
  }: {
    legendMode: ColorBy;
    clusterRows: ClusterLegendRow[];
    categoryRows: CategoryLegendRow[];
    clusterStats: { total: number; noise: number };
    categoryTitle: string;
    categoryTotal: number;
    legendFiltered: boolean;
    hidden: ReadonlySet<number>;
    isDark: boolean;
    onPickCluster: (id: number) => void | Promise<void>;
    onPickCategory: (code: number) => void | Promise<void>;
    onToggleHidden: (code: number) => void;
    onShowAll: () => void;
  } = $props();
</script>

<!-- legend / distribution (clickable → select) -->
{#if legendMode === 'cluster' && clusterRows.length}
  <div
    class="absolute right-3 top-3 max-h-[60%] w-52 overflow-y-auto rounded-md bg-card/85 p-2 text-[11px] shadow-sm backdrop-blur"
  >
    <div class="mb-1 flex items-center gap-2">
      <span class="font-medium text-muted-foreground"
        >Clusters · {clusterStats.total.toLocaleString()}</span
      >
      {#if hidden.size > 0}
        <button
          type="button"
          class="ml-auto rounded px-1 py-0.5 text-primary hover:bg-secondary/50"
          onclick={() => onShowAll()}
          title="Show all hidden clusters"
        >
          Show all
        </button>
      {/if}
    </div>
    {#each clusterRows as c (c.id)}
      {@const isHidden = hidden.has(c.id)}
      <div
        class="relative flex w-full items-center gap-1 overflow-hidden rounded px-1 py-0.5 hover:bg-secondary/50"
        class:opacity-40={isHidden}
      >
        <span
          class="pointer-events-none absolute inset-y-0 left-0 rounded-sm"
          style:width="{(c.frac * 100).toFixed(1)}%"
          style:background={c.color}
          style:opacity="0.16"
        ></span>
        <button
          type="button"
          class="relative flex flex-1 items-center gap-2 text-left"
          onclick={() => onPickCluster(c.id)}
          title="Select cluster #{c.id}"
        >
          <span class="size-2.5 shrink-0 rounded-full" style:background={c.color}></span>
          <span class="text-foreground">#{c.id}</span>
          <span class="ml-auto font-mono text-muted-foreground">{c.count.toLocaleString()}</span>
        </button>
        <button
          type="button"
          class="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
          onclick={() => onToggleHidden(c.id)}
          title={isHidden ? 'Show cluster on map' : 'Hide cluster on map'}
        >
          {#if isHidden}
            <EyeOff class="size-3.5" />
          {:else}
            <Eye class="size-3.5" />
          {/if}
        </button>
      </div>
    {/each}
    {#if clusterStats.noise > 0}
      {@const noiseHidden = hidden.has(-1)}
      <div
        class="mt-1 flex w-full items-center gap-1 rounded border-t border-border/60 px-1 pt-1 hover:bg-secondary/50"
        class:opacity-40={noiseHidden}
      >
        <button
          type="button"
          class="flex flex-1 items-center gap-2 text-left text-muted-foreground"
          onclick={() => onPickCluster(-1)}
          title="Select the unclustered (noise) points"
        >
          <span
            class="size-2.5 shrink-0 rounded-full"
            style:background={isDark ? '#52525b' : '#cccccc'}
          ></span>
          <span>noise (unclustered)</span>
          <span class="ml-auto font-mono">{clusterStats.noise.toLocaleString()}</span>
        </button>
        <button
          type="button"
          class="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
          onclick={() => onToggleHidden(-1)}
          title={noiseHidden ? 'Show noise on map' : 'Hide noise on map'}
        >
          {#if noiseHidden}
            <EyeOff class="size-3.5" />
          {:else}
            <Eye class="size-3.5" />
          {/if}
        </button>
      </div>
    {/if}
  </div>
{:else if categoryRows.length}
  <div
    class="absolute right-3 top-3 max-h-[60%] w-60 overflow-y-auto rounded-md bg-card/85 p-2 text-[11px] shadow-sm backdrop-blur"
  >
    <div class="mb-1 flex items-center gap-2">
      <span class="font-medium text-muted-foreground">
        {categoryTitle} · {legendFiltered
          ? `${categoryRows.length} of ${categoryTotal.toLocaleString()}`
          : categoryTotal.toLocaleString()}
      </span>
      {#if hidden.size > 0}
        <button
          type="button"
          class="ml-auto rounded px-1 py-0.5 text-primary hover:bg-secondary/50"
          onclick={() => onShowAll()}
          title="Show all hidden"
        >
          Show all
        </button>
      {/if}
    </div>
    {#each categoryRows as c (c.code)}
      {@const isHidden = hidden.has(c.code)}
      <div
        class="relative flex w-full items-center gap-1 overflow-hidden rounded px-1 py-0.5 hover:bg-secondary/50"
        class:opacity-60={c.empty}
        class:opacity-40={isHidden}
      >
        <span
          class="pointer-events-none absolute inset-y-0 left-0 rounded-sm"
          style:width="{(c.frac * 100).toFixed(1)}%"
          style:background={c.color}
          style:opacity="0.16"
        ></span>
        <button
          type="button"
          class="relative flex flex-1 items-center gap-2 text-left"
          onclick={() => onPickCategory(c.code)}
          title="Select {c.label}"
        >
          <span class="size-2.5 shrink-0 rounded-full" style:background={c.color}></span>
          <span class="truncate text-foreground" class:uppercase={legendMode === 'language'}
            >{c.label}</span
          >
          <span class="ml-auto shrink-0 font-mono text-muted-foreground"
            >{c.count.toLocaleString()}</span
          >
        </button>
        <button
          type="button"
          class="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
          onclick={() => onToggleHidden(c.code)}
          title={isHidden ? 'Show on map' : 'Hide on map'}
        >
          {#if isHidden}
            <EyeOff class="size-3.5" />
          {:else}
            <Eye class="size-3.5" />
          {/if}
        </button>
      </div>
    {/each}
  </div>
{/if}
