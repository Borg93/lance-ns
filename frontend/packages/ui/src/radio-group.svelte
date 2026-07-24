<script lang="ts" module>
  export type RadioOption = { value: string; label: string; description?: string };
</script>

<script lang="ts">
  import { RadioGroup } from 'bits-ui';
  import { cn } from './utils';

  let {
    value = $bindable(''),
    options,
    class: className,
  }: { value?: string; options: RadioOption[]; class?: string } = $props();
</script>

<RadioGroup.Root bind:value data-slot="radio-group" class={cn('grid gap-1', className)}>
  {#each options as opt (opt.value)}
    <label
      class="flex cursor-pointer items-start gap-2 rounded p-1.5 transition-colors hover:bg-secondary/40"
    >
      <RadioGroup.Item
        value={opt.value}
        class="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border border-border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=checked]:border-primary"
      >
        {#snippet children({ checked })}
          {#if checked}<span class="size-2 rounded-full bg-primary"></span>{/if}
        {/snippet}
      </RadioGroup.Item>
      <span class="flex-1 text-xs">
        <span class="font-medium text-foreground">{opt.label}</span>
        {#if opt.description}
          <span class="block text-muted-foreground">{opt.description}</span>
        {/if}
      </span>
    </label>
  {/each}
</RadioGroup.Root>
