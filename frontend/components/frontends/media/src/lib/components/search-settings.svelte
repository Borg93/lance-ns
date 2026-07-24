<script lang="ts">
  import { Popover } from 'bits-ui';
  import { Settings2 } from 'lucide-svelte';
  import { voiceSearch } from '$lib/voice-search.svelte';
  import {
    Field,
    Select,
    Switch,
    Slider,
    RadioGroup,
    type SelectOption,
    type RadioOption,
  } from '@lance/ui';

  /**
   * The single "config" surface for a search. All values are bindable and owned
   * by the parent <SearchBar>; they take effect on the next Search submit (the
   * query box and these settings are applied together).
   *
   * `kind` is read-only here — it decides which sections are relevant (balance
   * only matters for Hybrid; match style only when keyword is involved).
   */
  let {
    kind,
    resultN = $bindable('100'),
    rerank = $bindable(false),
    rerankN = $bindable('20'),
    weightPct = $bindable<number | null>(null),
    style = $bindable('loose'),
    sceneMethod = $bindable('vector'),
  }: {
    kind: string;
    resultN?: string;
    rerank?: boolean;
    rerankN?: string;
    weightPct?: number | null;
    style?: string;
    sceneMethod?: string;
  } = $props();

  const resultOptions: SelectOption[] = [20, 50, 100, 200].map((n) => ({
    value: String(n),
    label: String(n),
  }));
  const rerankOptions: SelectOption[] = [10, 20, 50, 100].map((n) => ({
    value: String(n),
    label: String(n),
  }));
  const matchOptions: RadioOption[] = [
    { value: 'loose', label: 'Loose', description: 'Words anywhere in the chunk; stem-aware.' },
    { value: 'phrase', label: 'Phrase', description: 'Exact words, consecutive order.' },
    { value: 'fuzzy', label: 'Fuzzy', description: 'Allow up to 2 typos per word.' },
  ];
  // How the Scene kind searches the frame caption: by meaning (vector) or words (BM25).
  const sceneOptions: RadioOption[] = [
    {
      value: 'vector',
      label: 'Meaning',
      description: 'Vector search over the caption — semantically similar scenes.',
    },
    {
      value: 'fts',
      label: 'Keyword',
      description: 'BM25 over the caption text — exact Swedish words in the scene description.',
    },
  ];

  // Balance is stored as weightPct ∈ [0,100] | null (null = parameter-free RRF).
  // Drive it from a local number + an "auto" switch so the Slider always sees a
  // number, then mirror back into the bindable weightPct.
  let auto = $state(weightPct === null);
  let weightVal = $state(weightPct ?? 50);
  $effect(() => {
    weightPct = auto ? null : weightVal;
  });

  const balanceLabel = $derived(
    auto
      ? 'Auto (RRF)'
      : weightVal === 50
        ? 'balanced'
        : weightVal < 50
          ? `${100 - weightVal}% keyword`
          : `${weightVal}% vector`,
  );
</script>

<Popover.Root>
  <Popover.Trigger
    class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground data-[state=open]:bg-muted data-[state=open]:text-foreground"
    title="Search settings — result count, reranking, fusion balance, match style"
  >
    <Settings2 class="size-3.5" />
    <span>Settings</span>
  </Popover.Trigger>

  <Popover.Portal>
    <Popover.Content
      sideOffset={6}
      align="end"
      class="z-50 flex w-[320px] flex-col gap-3 rounded-md border border-border bg-card p-4 text-xs shadow-md"
    >
      <Field label="Results to return" inline>
        <Select
          bind:value={resultN}
          options={resultOptions}
          ariaLabel="Results to return"
          class="w-24"
        />
      </Field>

      <Field label="Rerank results" inline>
        <Switch bind:checked={rerank} aria-label="Rerank results" />
      </Field>
      {#if rerank}
        <Field
          label="Rerank top"
          description="Cross-encoder re-scores this many top results (the rest keep their order). Smaller = faster, more precise head."
          inline
        >
          <Select
            bind:value={rerankN}
            options={rerankOptions}
            ariaLabel="Rerank candidates"
            class="w-24"
          />
        </Field>
      {/if}

      {#if kind === 'both'}
        <div class="flex flex-col gap-1.5 border-t border-border pt-3">
          <div class="flex items-baseline justify-between">
            <span class="text-xs font-medium text-foreground">Fusion balance</span>
            <span class="text-[11px] text-muted-foreground">{balanceLabel}</span>
          </div>
          <label class="flex items-center justify-between">
            <span class="text-[11px] text-muted-foreground">Auto-fuse (RRF)</span>
            <Switch bind:checked={auto} aria-label="Auto-fuse with RRF" />
          </label>
          {#if !auto}
            <Slider bind:value={weightVal} min={0} max={100} step={5} aria-label="Fusion balance" />
            <div class="flex justify-between text-[10px] text-muted-foreground">
              <span>← keyword</span>
              <span>vector →</span>
            </div>
          {/if}
        </div>
      {/if}

      {#if kind === 'scene'}
        <Field
          label="Scene search"
          description="Search the AI caption of each frame by meaning (vector) or exact words (keyword)."
          class="border-t border-border pt-3"
        >
          <RadioGroup bind:value={sceneMethod} options={sceneOptions} />
        </Field>
      {/if}

      {#if kind !== 'meaning' && kind !== 'scene'}
        <Field label="Keyword match style" class="border-t border-border pt-3">
          <RadioGroup bind:value={style} options={matchOptions} />
        </Field>
      {/if}

      {#if voiceSearch.built}
        <!-- Voice search ("Find this voice") is query-by-example, not a text
             mode — its only knob lives here. Bound straight to the shared
             store; the search page re-runs an active voice query on change. -->
        <div class="flex flex-col gap-1 border-t border-border pt-3">
          <Field label="Voice: include same video" inline>
            <Switch
              bind:checked={voiceSearch.includeSameDoc}
              aria-label="Voice results: include the anchor's own video"
            />
          </Field>
          <span class="text-[11px] text-muted-foreground">
            "Find this voice" normally hides matches from the anchor's own video. Applies
            immediately to an active voice search.
          </span>
        </div>
      {/if}
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>
