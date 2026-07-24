<script lang="ts">
  // Full columns/sort table of the unit's annotations — the review queue as a
  // spreadsheet (ported from the pre-monorepo AnnotationTable, commit 6afcbc7, which
  // the apps/media move dropped). Reads the controller's rows (no own fetch); click a
  // row to select it on the canvas; click a header to sort.
  import { cn } from '@lance/ui/utils';
  import { ChevronUp, ChevronDown } from 'lucide-svelte';
  import { statusDot } from './statusStyle';
  import type { AnnotatorController, AnnoRow } from '../annotator.svelte';

  let { controller }: { controller: AnnotatorController } = $props();

  type SortKey = 'label' | 'shape' | 'status' | 'confidence' | 'uncertainty';
  const NUMERIC: SortKey[] = ['confidence', 'uncertainty'];
  let sortKey = $state<SortKey>('uncertainty');
  let sortDir = $state<1 | -1>(-1);

  function toggleSort(k: SortKey): void {
    if (sortKey === k) sortDir = sortDir === 1 ? -1 : 1;
    else {
      sortKey = k;
      sortDir = NUMERIC.includes(k) ? -1 : 1;
    }
  }

  const sorted = $derived(
    controller.rows.toSorted((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      if (typeof av === 'number' || typeof bv === 'number') {
        return ((av as number) - (bv as number)) * sortDir;
      }
      return String(av).localeCompare(String(bv)) * sortDir;
    }),
  );

  const cols: { key: SortKey; label: string; num?: boolean }[] = [
    { key: 'label', label: 'Label' },
    { key: 'shape', label: 'Shape' },
    { key: 'status', label: 'Status' },
    { key: 'confidence', label: 'Conf', num: true },
    { key: 'uncertainty', label: 'Unc', num: true },
  ];
  const fmt = (n: number | null): string => (n == null ? '—' : n.toFixed(2));
</script>

<div class="flex min-h-0 flex-1 flex-col overflow-hidden text-xs" data-testid="annotation-table">
  <div class="overflow-auto">
    <table class="w-full border-collapse">
      <thead
        class="sticky top-0 z-10 bg-muted/70 text-left text-[10px] uppercase text-muted-foreground backdrop-blur"
      >
        <tr>
          {#each cols as c (c.key)}
            <th class={cn('px-2 py-1.5 font-medium', c.num && 'text-right')}>
              <button
                class="inline-flex items-center gap-0.5 hover:text-foreground"
                onclick={() => toggleSort(c.key)}
              >
                {c.label}
                {#if sortKey === c.key}
                  {#if sortDir === 1}<ChevronUp class="size-3" />{:else}<ChevronDown class="size-3" />{/if}
                {/if}
              </button>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each sorted as r (r.index)}
          <tr
            class={cn(
              'cursor-pointer border-b border-border/50 hover:bg-muted/50',
              controller.selectedIndex === r.index && 'bg-primary/10',
            )}
            onclick={() => controller.select(r.index)}
          >
            <td class="max-w-28 truncate px-2 py-1" title={r.label}>{r.label || `#${r.index}`}</td>
            <td class="px-2 py-1 text-muted-foreground">{r.shape || '—'}</td>
            <td class="px-2 py-1">
              <span class="inline-flex items-center gap-1">
                <span class={cn('size-2 rounded-full', statusDot(r.status))}></span>
                {r.status || '—'}
              </span>
            </td>
            <td class="px-2 py-1 text-right tabular-nums text-muted-foreground">{fmt(r.confidence)}</td>
            <td class="px-2 py-1 text-right tabular-nums text-muted-foreground">{fmt(r.uncertainty)}</td>
          </tr>
        {:else}
          <tr><td colspan={cols.length} class="px-3 py-6 text-center text-muted-foreground">No annotations</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
