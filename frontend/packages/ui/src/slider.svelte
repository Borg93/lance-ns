<script lang="ts">
  import { Slider } from 'bits-ui';
  import { cn } from './utils';

  let {
    value = $bindable(50),
    min = 0,
    max = 100,
    step = 1,
    class: className,
    ...rest
  }: {
    value?: number;
    min?: number;
    max?: number;
    step?: number;
    class?: string;
    'aria-label'?: string;
    /** Fires on user interaction only (not programmatic value changes) — lets a
     *  controlled scrubber seek without a bind:value ↔ update loop. */
    onValueChange?: (value: number) => void;
  } = $props();
</script>

<Slider.Root
  type="single"
  bind:value
  {min}
  {max}
  {step}
  data-slot="slider"
  class={cn('relative flex w-full touch-none items-center select-none', className)}
  {...rest}
>
  {#snippet children({ thumbs })}
    <span class="relative h-1.5 w-full grow overflow-hidden rounded-full bg-secondary">
      <Slider.Range class="absolute h-full bg-primary" />
    </span>
    {#each thumbs as index (index)}
      <Slider.Thumb
        {index}
        class="block size-4 rounded-full border-2 border-primary bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    {/each}
  {/snippet}
</Slider.Root>
