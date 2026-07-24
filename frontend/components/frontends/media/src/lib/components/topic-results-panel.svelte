<script lang="ts">
  /**
   * Results panel for the Tree page: the chunks tagged with the clicked topic,
   * browsable and playable in place (no hand-off). "Open in Search" continues
   * to the full Search UI with the same topic filter for refining.
   *
   * Backed by the topic-only browse branch of `/api/search` (empty query +
   * `topic=`), the same call the Search page makes for `/?topic=<name>`.
   */
  import { ArrowLeft, ArrowUpRight, X } from 'lucide-svelte';
  import { search, type Hit } from '@lance/api';
  import HitList from './hit-list.svelte';
  import PlayerPane from './player-pane.svelte';

  let { topic, onClose }: { topic: string; onClose: () => void } = $props();

  const BROWSE_N = 100;

  let hits = $state<Hit[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let active = $state<Hit | null>(null);

  $effect(() => {
    const name = topic; // tracked: refetch when another topic is clicked
    let cancelled = false;
    loading = true;
    error = null;
    active = null;
    // Drop the previous topic's hits immediately — keeping them rendered the
    // old list under the NEW topic's header until the fetch landed.
    hits = [];
    (async () => {
      try {
        const res = await search({ q: '', topic: name, n: BROWSE_N, mode: 'fts' });
        if (!cancelled) hits = res;
      } catch (e) {
        if (!cancelled) error = e instanceof Error ? e.message : String(e);
      } finally {
        if (!cancelled) loading = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

<div class="flex h-full min-h-0 flex-col border-l border-border bg-card">
  <header class="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
    {#if active}
      <button
        type="button"
        onclick={() => (active = null)}
        aria-label="Back to topic results"
        class="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft class="size-4" />
      </button>
    {/if}
    <span class="min-w-0 truncate text-sm font-medium text-foreground" title={topic}>{topic}</span>
    {#if !loading && !error}
      <span class="shrink-0 text-xs text-muted-foreground">
        · {hits.length}{hits.length === BROWSE_N ? '+' : ''} chunks
      </span>
    {/if}
    <a
      href={`/?topic=${encodeURIComponent(topic)}`}
      class="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      title="Refine this topic in the full Search UI"
    >
      Open in Search <ArrowUpRight class="size-3" />
    </a>
    <button
      type="button"
      onclick={onClose}
      aria-label="Close topic results"
      class="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <X class="size-4" />
    </button>
  </header>

  <div class="min-h-0 flex-1 overflow-y-auto">
    {#if active}
      <PlayerPane hit={active} />
    {:else if error}
      <div class="px-4 py-6 text-sm text-destructive">Failed to load topic: {error}</div>
    {:else}
      <HitList
        {hits}
        {active}
        onselect={(h) => (active = h)}
        emptyMessage={loading ? 'Loading…' : 'No chunks carry this topic.'}
      />
    {/if}
  </div>
</div>
