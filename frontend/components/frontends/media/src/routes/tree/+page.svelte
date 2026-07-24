<script lang="ts">
  /**
   * Tree tab — the topic hierarchy as a zoomable treemap (or Sankey flow).
   *
   * `ratch feature topics` clusters chunks (Toponymy) and stores the nested
   * hierarchy as Lance JSONB in `topics.lance`; `/api/topics` serves it. We gate
   * on `built` (pointing the user at the build step otherwise) and render
   * <TopicTreemap>. Clicking a topic opens its results in a side panel
   * (<TopicResultsPanel>), playable in place; "Open in Search" continues to
   * `/?topic=<name>` for refining.
   *
   * A dedicated route — separate from Search and Atlas, sharing only the topic
   * filter on `/api/search`.
   */
  import { browser } from '$app/environment';
  import { getTopics, type TopicNode } from '@lance/api';
  import TopicTreemap from '$lib/components/topic-treemap.svelte';
  import TopicResultsPanel from '$lib/components/topic-results-panel.svelte';
  import ResizableSplit from '@lance/ui/resizable-split.svelte';

  type Phase = 'loading' | 'ready' | 'unavailable' | 'error';

  let phase = $state<Phase>('loading');
  let errorMsg = $state<string | null>(null);
  let hierarchy = $state<TopicNode | null>(null);
  let noiseLabel = $state('');
  /** Topic whose results show in the side panel (null = full-width map). */
  let selectedTopic = $state<string | null>(null);

  $effect(() => {
    if (!browser) return;
    let cancelled = false;

    (async () => {
      try {
        const res = await getTopics();
        if (cancelled) return;
        if (!res.built || !res.hierarchy) {
          phase = 'unavailable';
          return;
        }
        hierarchy = res.hierarchy;
        noiseLabel = res.noise_label ?? ''; // '' (no match) on an older backend
        phase = 'ready';
      } catch (e) {
        if (!cancelled) {
          errorMsg = e instanceof Error ? e.message : String(e);
          phase = 'error';
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  });
</script>

<div class="h-full w-full">
  {#if phase === 'unavailable'}
    <div class="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">
      <div>
        <p class="mb-1 font-medium text-foreground">No topics yet</p>
        <p>
          Run <code class="rounded bg-muted px-1 py-0.5">ratch feature topics</code> to cluster the chunks
          into a topic hierarchy.
        </p>
      </div>
    </div>
  {:else if phase === 'error'}
    <div class="grid h-full place-items-center p-6 text-center text-sm text-destructive">
      Failed to load topics: {errorMsg}
    </div>
  {:else if phase === 'ready' && hierarchy}
    <!-- `tree` re-binds the narrowed value: the {#if} guard's narrowing does
         not flow into the snippet bodies (they are functions). -->
    {@const tree = hierarchy}
    <!-- Map + results, draggable divider (same split as the Search page). The
         split is always mounted so the treemap's drill/view state survives
         topic clicks; the right pane swaps hint ↔ results. -->
    <ResizableSplit storageKey="lance-media-tree-split" initial={0.68} minLeft={420} minRight={300}>
      {#snippet left()}
        <TopicTreemap
          hierarchy={tree}
          {noiseLabel}
          onShowResults={(name) => (selectedTopic = name)}
        />
      {/snippet}
      {#snippet right()}
        {#if selectedTopic}
          <TopicResultsPanel topic={selectedTopic} onClose={() => (selectedTopic = null)} />
        {:else}
          <div
            class="grid h-full place-items-center border-l border-border bg-card p-6 text-center text-xs text-muted-foreground"
          >
            Click a topic to browse its chunks here.
          </div>
        {/if}
      {/snippet}
    </ResizableSplit>
  {:else}
    <div class="grid h-full place-items-center text-sm text-muted-foreground">Loading…</div>
  {/if}
</div>
