<script lang="ts">
  // The search-bar `?` — a small popover with click-to-run examples + tips that
  // make search easier. The deep "how it works" walk-through now lives on the
  // Guide page (linked at the bottom), so this stays compact.
  import { Popover } from 'bits-ui';
  import { HelpCircle, ArrowRight, Image as ImageIcon } from 'lucide-svelte';

  type Example = { label: string; example: string; explain: string };
  type Props = {
    examples: Record<string, Example>;
    /** Called when the user clicks an example row — fires (key, example). */
    onpick?: (key: string, example: string) => void;
  };
  let { examples, onpick }: Props = $props();

  let open = $state(false);

  function pick(key: string, example: string) {
    onpick?.(key, example);
    open = false; // filled the query box — close so results are visible
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger
    class="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/40 hover:text-foreground"
    title="Examples & tips"
  >
    <HelpCircle class="size-4" />
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content
      side="bottom"
      align="end"
      sideOffset={6}
      class="z-50 w-[min(92vw,400px)] rounded-lg border border-border bg-card p-3 text-xs shadow-md"
    >
      <div class="mb-1.5 font-medium text-foreground">Try an example</div>
      <div class="grid gap-0.5">
        {#each Object.entries(examples) as [key, info] (key)}
          <button
            type="button"
            onclick={() => pick(key, info.example)}
            class="grid grid-cols-[84px_1fr] items-baseline gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-secondary/50"
          >
            <span class="font-medium text-foreground">{info.label}</span>
            <span class="min-w-0">
              <code class="rounded bg-surface2 px-1.5 py-0.5 font-mono text-[11px] text-primary">
                {info.example}
              </code>
              <span class="mt-0.5 block text-muted-foreground">{info.explain}</span>
            </span>
          </button>
        {/each}
      </div>

      <div
        class="mt-2 flex items-start gap-1.5 rounded border border-dashed border-border bg-muted/40 p-2 text-muted-foreground"
      >
        <ImageIcon class="mt-0.5 size-3.5 shrink-0" />
        <span
          ><strong class="text-foreground">Attach an image</strong> (📎 or drag in) to add a visual pass.</span
        >
      </div>

      <a
        href="/guide"
        onclick={() => (open = false)}
        class="mt-2 flex items-center gap-1.5 rounded px-2 py-1.5 font-medium text-primary transition-colors hover:bg-secondary/50"
      >
        Full guide: how search works
        <ArrowRight class="size-3.5" />
      </a>
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
