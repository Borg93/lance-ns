<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn, type WithElementRef } from '../utils';
  import { useSidebar } from './context.svelte.js';

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: WithElementRef<HTMLAttributes<HTMLButtonElement>, HTMLButtonElement> = $props();

  const sidebar = useSidebar();
</script>

<button
  bind:this={ref}
  data-slot="sidebar-rail"
  data-sidebar="rail"
  aria-label="Toggle sidebar"
  tabindex={-1}
  onclick={() => sidebar.toggle()}
  title="Toggle sidebar"
  class={cn(
    'absolute inset-y-0 z-20 hidden w-4 -translate-x-1/2 transition-all ease-linear after:absolute after:inset-y-0 after:left-1/2 after:w-[2px] hover:after:bg-sidebar-border sm:flex',
    'group-data-[side=left]:-right-4 group-data-[side=right]:left-0',
    'group-data-[side=left]:cursor-w-resize group-data-[side=right]:cursor-e-resize',
    'group-data-[collapsible=icon]:cursor-e-resize',
    className,
  )}
  {...restProps}
></button>
