<script lang="ts">
	// Thin annotator route. `?keys=doc/speech/chunk,…` (the read plane's review-selection
	// bridge — atlas lasso / search — and now also this zone's own selection view) opens
	// the annotate canvas, re-mounted per active key so navigating the selection loads
	// each unit fresh. With no keys the DATA-SELECTION landing renders instead (datasets →
	// documents → chunks); the old hardcoded demo unit is gone. The URL is the source of
	// truth, so a canvas reload restores the same unit.
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { MediaKind } from '$lib/viewer/types';
	import { reviewSelection } from '$lib/labeling/review-selection.svelte';
	import DataSelection from '$lib/select/DataSelection.svelte';
	import AnnotatorShell from '$lib/viewer/layout/AnnotatorShell.svelte';

	function openFromParams(params: URLSearchParams): void {
		const keys = params.get('keys');
		if (!keys) {
			reviewSelection.clear();
			return;
		}
		// Beyond `keys`, the deep-link takes a modality override (`kind=audio|video` → the
		// temporal viewers) and an optional same-origin `media=` source (a specific clip).
		const rawKind = params.get('kind');
		const kind: MediaKind = rawKind === 'audio' || rawKind === 'video' ? rawKind : 'image';
		const rawMedia = params.get('media');
		const media = rawMedia?.startsWith('/') ? rawMedia : undefined; // same-origin only
		reviewSelection.openKeys(keys.split(','), kind, media);
	}

	// Init synchronously (before first render) so a deep link never flashes the landing.
	if (browser) openFromParams(new URLSearchParams(window.location.search));

	// Track later URL changes (selection-view goto, back/forward) — guarded against
	// re-opening the keys the store already holds. The param is normalized exactly like
	// openKeys (empty segments dropped), otherwise a hand-edited link such as
	// `?keys=doc/0/1,` would never equal the held keys and the effect would loop.
	$effect(() => {
		const wanted = (page.url.searchParams.get('keys') ?? '').split(',').filter(Boolean).join(',');
		const held = reviewSelection.units.map((u) => u.key).join(',');
		if (wanted !== held) openFromParams(page.url.searchParams);
	});

	const unit = $derived(reviewSelection.active);

	function open(keys: string[]): void {
		void goto(`?keys=${encodeURIComponent(keys.join(','))}`, { keepFocus: true, noScroll: true });
	}
	function exit(): void {
		void goto('?', { keepFocus: true, noScroll: true });
	}
</script>

{#if unit}
	{#key unit.key}
		<AnnotatorShell {unit} onexit={exit} />
	{/key}
{:else}
	<DataSelection onopen={open} />
{/if}
