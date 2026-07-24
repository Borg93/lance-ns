<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn, type WithElementRef } from '../utils';
  import { useSidebar } from './context.svelte.js';

  let {
    ref = $bindable(null),
    side = 'left',
    collapsible = 'icon',
    class: className,
    children,
    ...restProps
  }: WithElementRef<HTMLAttributes<HTMLDivElement>> & {
    side?: 'left' | 'right';
    collapsible?: 'offcanvas' | 'icon' | 'none';
  } = $props();

  const sidebar = useSidebar();
</script>

{#if collapsible === 'none'}
  <div
    bind:this={ref}
    data-slot="sidebar"
    class={cn(
      'bg-sidebar text-sidebar-foreground flex h-full w-(--sidebar-width) flex-col',
      className,
    )}
    {...restProps}
  >
    {@render children?.()}
  </div>
{:else}
  <div
    bind:this={ref}
    class="group peer text-sidebar-foreground block"
    data-slot="sidebar"
    data-state={sidebar.state}
    data-collapsible={sidebar.state === 'collapsed' ? collapsible : ''}
    data-side={side}
  >
    <!-- the gap that pushes content; shrinks to icon width / 0 when collapsed -->
    <div
      data-slot="sidebar-gap"
      class={cn(
        'relative w-(--sidebar-width) bg-transparent transition-[width] duration-200 ease-linear',
        'group-data-[collapsible=offcanvas]:w-0',
        'group-data-[side=right]:rotate-180',
        'group-data-[collapsible=icon]:w-(--sidebar-width-icon)',
      )}
    ></div>
    <div
      data-slot="sidebar-container"
      class={cn(
        'fixed inset-y-0 z-10 flex h-svh w-(--sidebar-width) transition-[left,right,width] duration-200 ease-linear',
        side === 'left'
          ? 'left-0 group-data-[collapsible=offcanvas]:left-[calc(var(--sidebar-width)*-1)]'
          : 'right-0 group-data-[collapsible=offcanvas]:right-[calc(var(--sidebar-width)*-1)]',
        'group-data-[collapsible=icon]:w-(--sidebar-width-icon)',
        'group-data-[side=left]:border-r group-data-[side=right]:border-l border-sidebar-border',
        className,
      )}
      {...restProps}
    >
      <div
        data-sidebar="sidebar"
        data-slot="sidebar-inner"
        class="bg-sidebar flex h-full w-full flex-col"
      >
        {@render children?.()}
      </div>
    </div>
  </div>
{/if}
