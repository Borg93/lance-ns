<script lang="ts">
  import '../app.css';
  import { onMount, type Snippet } from 'svelte';
  import { browser } from '$app/environment';
  import { page } from '$app/state';
  import { descriptor } from '$lib/descriptor-store.svelte';
  import {
    AudioLines,
    Search,
    Map,
    FolderTree,
    Share2,
    BookOpen,
    Workflow,
    SquarePen,
    type Icon as LucideIcon,
  } from 'lucide-svelte';
  import * as Sidebar from '@lance/ui/sidebar';
  import ThemeToggle from '$lib/components/theme-toggle.svelte';
  import StatusBadge from '$lib/components/status-badge.svelte';

  let { children }: { children: Snippet } = $props();

  // `typeof LucideIcon` (not Svelte 5's `Component<…>`): lucide-svelte 0.468
  // still types its icons as legacy class components, so this is the accurate
  // common type for this dependency version.
  const NAV: { href: string; label: string; icon: typeof LucideIcon; hint: string }[] = [
    {
      href: '/',
      label: 'Search',
      icon: Search,
      hint: 'Find moments across transcripts, video & scenes',
    },
    { href: '/atlas', label: 'Atlas', icon: Map, hint: 'Explore the embedding map of every chunk' },
    { href: '/tree', label: 'Tree', icon: FolderTree, hint: 'Browse topics as a zoomable treemap' },
    {
      href: '/graph',
      label: 'Graph',
      icon: Share2,
      hint: 'Explore the knowledge graph — entities, relations & clips',
    },
    {
      href: '/workflow',
      label: 'Workflow',
      icon: Workflow,
      hint: 'Build & run a retrieval pipeline as a node graph',
    },
    {
      href: '/annotate',
      label: 'Annotate',
      icon: SquarePen,
      hint: 'View & annotate documents/HTR — canvas + review-queue table',
    },
    {
      href: '/guide',
      label: 'Guide',
      icon: BookOpen,
      hint: 'How search works — signals, fusion & rerank',
    },
  ];

  // '/' must match exactly; deeper routes match on prefix so nested pages stay active.
  const isActive = (href: string): boolean =>
    href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);

  const current = $derived(NAV.find((n) => isActive(n.href)));

  // Restore the collapsed/expanded state the provider persists to a cookie.
  function initialOpen(): boolean {
    if (!browser) return true;
    const m = document.cookie.match(/(?:^|;\s*)sidebar:state=(true|false)/);
    return m ? m[1] === 'true' : true;
  }
  let sidebarOpen = $state(initialOpen());

  // Load the dataset descriptor once before rendering any route — every
  // renderer reads the active DatasetView, so it must be set first.
  onMount(() => {
    void descriptor.load();
  });
</script>

<Sidebar.Provider bind:open={sidebarOpen} class="h-svh overflow-hidden">
  <Sidebar.Root collapsible="icon">
    <!-- header -->
    <div data-slot="sidebar-header" class="flex flex-col gap-2 p-2">
      <a
        href="/"
        title="lance-media — home"
        aria-label="lance-media home"
        class="hover:bg-sidebar-accent flex items-center gap-2 rounded-md p-1.5 transition-colors"
      >
        <div class="bg-primary/10 text-primary grid size-8 shrink-0 place-items-center rounded-lg">
          <AudioLines class="size-5" />
        </div>
        <div class="flex min-w-0 flex-col leading-tight group-data-[collapsible=icon]:hidden">
          <span class="text-foreground truncate text-sm font-semibold">lance-media</span>
          <span class="text-muted-foreground truncate text-[10px]">press-conf viewer</span>
        </div>
      </a>
    </div>

    <!-- content -->
    <div
      data-slot="sidebar-content"
      class="flex min-h-0 flex-1 flex-col gap-2 overflow-auto group-data-[collapsible=icon]:overflow-hidden"
    >
      <div data-slot="sidebar-group" class="relative flex w-full min-w-0 flex-col p-2">
        <div
          data-slot="sidebar-group-label"
          class="text-sidebar-foreground/60 flex h-8 shrink-0 items-center rounded-md px-2 text-xs font-medium tracking-wide uppercase transition-[margin,opacity] duration-200 ease-linear group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0"
        >
          Navigate
        </div>
        <ul data-slot="sidebar-menu" class="flex w-full min-w-0 flex-col gap-1">
          {#each NAV as item (item.href)}
            {@const active = isActive(item.href)}
            {@const Icon = item.icon}
            <li data-slot="sidebar-menu-item" class="group/menu-item relative">
              <Sidebar.MenuButton href={item.href} isActive={active} tooltip={item.label}>
                <Icon />
                <span>{item.label}</span>
              </Sidebar.MenuButton>
            </li>
          {/each}
        </ul>
      </div>
    </div>

    <!-- footer -->
    <div data-slot="sidebar-footer" class="flex flex-col gap-2 p-2">
      <div
        class="flex items-center justify-between gap-1 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:gap-2"
      >
        <StatusBadge />
        <ThemeToggle />
      </div>
    </div>
    <Sidebar.Rail />
  </Sidebar.Root>

  <Sidebar.Inset class="h-svh overflow-hidden">
    <header class="border-border flex h-11 shrink-0 items-center gap-2 border-b px-3">
      <Sidebar.Trigger />
      <div class="bg-border h-4 w-px"></div>
      {#if current}
        {@const Icon = current.icon}
        <Icon class="text-muted-foreground size-4" />
        <span class="text-foreground text-sm font-medium">{current.label}</span>
        <span class="text-muted-foreground hidden truncate text-xs sm:inline">— {current.hint}</span
        >
      {/if}
    </header>
    <div class="min-h-0 flex-1 overflow-hidden">
      {#if descriptor.view}
        {@render children()}
      {:else if descriptor.error}
        <div class="grid h-full place-items-center p-6 text-center">
          <div class="max-w-md">
            <p class="text-foreground text-sm font-medium">Could not load the dataset descriptor</p>
            <p class="text-muted-foreground mt-1 text-xs">{descriptor.error}</p>
          </div>
        </div>
      {:else}
        <div class="text-muted-foreground grid h-full place-items-center text-sm">Loading dataset…</div>
      {/if}
    </div>
  </Sidebar.Inset>
</Sidebar.Provider>
