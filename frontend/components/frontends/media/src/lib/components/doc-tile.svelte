<script lang="ts">
  import { thumbnailUrl, type Document } from '@lance/api';
  import { activeView } from '@lance/api/descriptor';
  import { fmtTime, cn } from '$lib/utils';

  type Props = {
    doc: Document;
    active?: boolean;
    onclick?: () => void;
  };
  let { doc, active = false, onclick }: Props = $props();

  // The active dataset view — title/duration/metadata come from the descriptor,
  // so this gallery tile renders any dataset's document schema.
  const view = activeView();
  const title = $derived(view.title(doc));
  const duration = $derived(view.duration(doc));
  // Declared metadata (label+value, empties dropped) minus any row that just
  // repeats the title, joined into one compact identifier line.
  const metaLine = $derived(
    view
      .metadata(doc)
      .filter((m) => m.value !== title)
      .map((m) => m.value)
      .join('  ·  '),
  );
</script>

<button
  type="button"
  {onclick}
  aria-pressed={active}
  class={cn(
    'group flex flex-col overflow-hidden rounded-lg border bg-card text-left transition-all',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
    active
      ? 'border-primary ring-2 ring-primary shadow-md -translate-y-0.5'
      : 'border-border hover:border-primary hover:shadow-md hover:-translate-y-0.5',
  )}
>
  <div class="relative aspect-video w-full overflow-hidden bg-muted">
    <img
      src={thumbnailUrl(doc)}
      alt=""
      loading="lazy"
      class="h-full w-full object-cover transition-transform group-hover:scale-105"
      onerror={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
    />
    {#if duration != null}
      <span
        class="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white backdrop-blur-sm"
      >
        {fmtTime(duration)}
      </span>
    {/if}
  </div>
  <div class="flex flex-1 flex-col gap-1 p-3">
    <div class="line-clamp-2 text-sm font-medium leading-snug">
      {title}
    </div>
    {#if metaLine}
      <div class="truncate font-mono text-[10px] text-muted-foreground" title={metaLine}>
        {metaLine}
      </div>
    {/if}
  </div>
</button>
