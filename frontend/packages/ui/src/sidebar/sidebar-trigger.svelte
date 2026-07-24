<script lang="ts">
  import { PanelLeft } from 'lucide-svelte';
  import type { ComponentProps } from 'svelte';
  import Button from '../button.svelte';
  import { cn } from '../utils';
  import { useSidebar } from './context.svelte.js';

  // Button's `onclick` is a button|anchor union; narrowing it to a plain
  // MouseEvent handler lets us forward the event without tripping
  // exactOptionalPropertyTypes on the union's currentTarget.
  let {
    ref = $bindable(null),
    class: className,
    onclick,
    ...restProps
  }: Omit<ComponentProps<typeof Button>, 'onclick'> & {
    onclick?: (e: MouseEvent) => void;
  } = $props();

  const sidebar = useSidebar();
</script>

<Button
  bind:ref
  data-sidebar="trigger"
  data-slot="sidebar-trigger"
  variant="ghost"
  size="icon"
  class={cn('size-8', className)}
  title="Toggle sidebar (⌘/Ctrl-B)"
  aria-label="Toggle sidebar"
  onclick={(e) => {
    onclick?.(e);
    sidebar.toggle();
  }}
  {...restProps}
>
  <PanelLeft />
  <span class="sr-only">Toggle sidebar</span>
</Button>
