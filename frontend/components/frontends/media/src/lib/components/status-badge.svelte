<script lang="ts">
  import { getHealth, type Health } from '@lance/api';
  import { Popover } from 'bits-ui';
  import { Activity } from 'lucide-svelte';

  let health = $state<Health | null>(null);
  let lastError = $state<string | null>(null);

  async function refresh() {
    try {
      health = await getHealth();
      lastError = null;
    } catch (e) {
      lastError = e instanceof Error ? e.message : 'fetch failed';
      health = null;
    }
  }

  $effect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  });

  /** Overall colour: green if both up, amber if one down, red if both down or backend unreachable. */
  const tone = $derived.by(() => {
    if (!health) return 'red';
    const up = (health.embed.ok ? 1 : 0) + (health.rerank.ok ? 1 : 0);
    return up === 2 ? 'green' : up === 1 ? 'amber' : 'red';
  });

  const dotClass = (ok: boolean | undefined) =>
    ok === undefined ? 'bg-muted-foreground/40' : ok ? 'bg-emerald-500' : 'bg-red-500';
</script>

<Popover.Root>
  <Popover.Trigger
    class="flex items-center gap-1.5 rounded px-2 py-1 text-[11px] hover:bg-secondary/60"
    title="Service status"
  >
    <span
      class="size-2 rounded-full {tone === 'green'
        ? 'bg-emerald-500'
        : tone === 'amber'
          ? 'bg-amber-500'
          : 'bg-red-500'}"
    ></span>
    <Activity class="size-3.5 text-muted-foreground" />
    <span class="hidden text-muted-foreground sm:inline group-data-[collapsible=icon]:!hidden"
      >services</span
    >
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content
      side="top"
      sideOffset={8}
      align="start"
      class="z-50 w-80 rounded-md border border-border bg-card p-3 text-xs shadow-md"
    >
      {#if lastError}
        <div class="text-destructive">Backend unreachable: {lastError}</div>
        <button
          type="button"
          class="mt-2 rounded border border-border px-2 py-1 hover:bg-secondary"
          onclick={refresh}
        >
          retry
        </button>
      {:else if !health}
        <div class="text-muted-foreground">Loading…</div>
      {:else}
        <div class="space-y-2">
          <div>
            <div class="mb-1 font-semibold text-foreground">vLLM services</div>
            <div class="flex items-center gap-2">
              <span class="size-2 rounded-full {dotClass(health.embed.ok)}"></span>
              <span class="font-mono text-[10px]">embed</span>
              <span class="ml-auto truncate font-mono text-[10px] text-muted-foreground">
                {health.embed.url}
              </span>
            </div>
            {#if !health.embed.ok && health.embed.error}
              <div class="ml-4 mt-0.5 text-[10px] text-destructive">{health.embed.error}</div>
            {/if}
            <div class="mt-1 flex items-center gap-2">
              <span class="size-2 rounded-full {dotClass(health.rerank.ok)}"></span>
              <span class="font-mono text-[10px]">rerank</span>
              <span class="ml-auto truncate font-mono text-[10px] text-muted-foreground">
                {health.rerank.url}
              </span>
            </div>
            {#if !health.rerank.ok && health.rerank.error}
              <div class="ml-4 mt-0.5 text-[10px] text-destructive">{health.rerank.error}</div>
            {/if}
          </div>

          <div class="border-t border-border pt-2">
            <div class="mb-1 font-semibold text-foreground">Lance dataset</div>
            <div class="font-mono text-[10px] text-muted-foreground break-all">
              {health.db.path}
            </div>
            <div class="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
              <span class="text-muted-foreground">tables</span>
              <span class="font-mono text-foreground">{health.db.tables.join(', ')}</span>
              <span class="text-muted-foreground">chunks</span>
              <span class="font-mono text-foreground">{health.db.chunks.toLocaleString()}</span>
              <span class="text-muted-foreground">documents</span>
              <span class="font-mono text-foreground">{health.db.documents.toLocaleString()}</span>
            </div>
          </div>

          <button
            type="button"
            class="w-full rounded border border-border px-2 py-1 hover:bg-secondary"
            onclick={refresh}
          >
            refresh
          </button>
        </div>
      {/if}
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
