<script lang="ts">
	// Bottom page-navigation bar. Controlled: renders a pages list + current index
	// and emits navigate. Document-plane today (pages); for audio/video this becomes
	// a segment/scene strip — same controlled contract. (Ported from ra-anno PageNavBar.)
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { Button } from '@lance/ui';

	export interface PageRef {
		key: string;
		label: string;
	}

	let {
		pages,
		current = 0,
		onNavigate,
	}: { pages: PageRef[]; current?: number; onNavigate?: (index: number) => void } = $props();

	const total = $derived(pages.length);
	const go = (i: number) => {
		if (i >= 0 && i < total) onNavigate?.(i);
	};
</script>

<nav
	class="border-border bg-card/90 pointer-events-auto absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-lg border px-1 py-0.5 shadow-md backdrop-blur"
	data-testid="page-nav"
>
	<Button
		variant="ghost"
		size="icon-xs"
		title="Previous page"
		disabled={current <= 0}
		onclick={() => go(current - 1)}
	>
		<ChevronLeft class="size-4" />
	</Button>
	<span class="text-muted-foreground px-1 text-xs tabular-nums">
		{total === 0 ? '0 / 0' : `${current + 1} / ${total}`}
	</span>
	<Button
		variant="ghost"
		size="icon-xs"
		title="Next page"
		disabled={current >= total - 1}
		onclick={() => go(current + 1)}
	>
		<ChevronRight class="size-4" />
	</Button>
</nav>
