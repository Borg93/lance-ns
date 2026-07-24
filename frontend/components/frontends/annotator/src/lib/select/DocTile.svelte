<script lang="ts">
	// One document card in the selection grid — thumbnail (cheap: the viewer's cached
	// /api/thumbnail blob), descriptor-driven title/metadata, duration badge. Dumb +
	// controlled, mirroring the media zone's gallery tile.
	import type { Document } from '@lance/api';
	import type { DatasetView } from '@lance/api/descriptor';
	import { cn } from '@lance/ui/utils';

	let { view, doc, onclick }: { view: DatasetView; doc: Document; onclick?: () => void } = $props();

	const title = $derived(view.title(doc));
	const duration = $derived(view.duration(doc));
	// Declared metadata minus any row that just repeats the title, as one compact line.
	const metaLine = $derived(
		view
			.metadata(doc)
			.filter((m) => m.value !== title)
			.map((m) => m.value)
			.join('  ·  '),
	);

	function fmtTime(s: number): string {
		const m = Math.floor(s / 60);
		return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
	}
</script>

<button
	type="button"
	{onclick}
	data-testid="doc-tile"
	class={cn(
		'group bg-card flex flex-col overflow-hidden rounded-lg border text-left transition-all',
		'border-border hover:border-primary focus-visible:ring-ring hover:-translate-y-0.5 hover:shadow-md focus-visible:ring-2 focus-visible:outline-none',
	)}
>
	<div class="bg-muted relative aspect-video w-full overflow-hidden">
		<img
			src={view.thumbnailUrl(doc)}
			alt=""
			loading="lazy"
			class="h-full w-full object-cover transition-transform group-hover:scale-105"
			onerror={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
		/>
		{#if duration != null}
			<span
				class="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white backdrop-blur-sm"
			>
				{fmtTime(duration)}
			</span>
		{/if}
	</div>
	<div class="flex flex-1 flex-col gap-1 p-3">
		<div class="line-clamp-2 text-sm leading-snug font-medium">{title}</div>
		{#if metaLine}
			<div class="text-muted-foreground truncate font-mono text-[10px]" title={metaLine}>
				{metaLine}
			</div>
		{/if}
	</div>
</button>
