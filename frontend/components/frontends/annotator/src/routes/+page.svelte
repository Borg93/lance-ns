<script lang="ts">
	// Thin annotator route: resolve the media unit(s) — a review SELECTION handed off
	// from the read plane via `?keys=doc/speech/chunk,…` (atlas lasso / search), else
	// the demo unit — and mount the shell PER unit (re-mount on the active key) so
	// navigating the selection loads each fresh. (RA_ANNO_MERGE.md §5c–5d.)
	import { browser } from '$app/environment';
	import type { MediaKind, MediaUnit } from '$lib/viewer/types';
	import { reviewSelection } from '$lib/labeling/review-selection.svelte';
	import AnnotatorShell from '$lib/viewer/layout/AnnotatorShell.svelte';

	const DEMO_KEY = 'fe00cd746463ad2c/0/19';
	const DEMO_UNIT: MediaUnit = {
		kind: 'image',
		key: DEMO_KEY,
		imageUrl: `/api/chunk-frame/${DEMO_KEY}`,
		annotationsUrl: `/api/annotations/${DEMO_KEY}`,
	};

	// Init synchronously (before first render) so there's no demo flash. Beyond `keys`,
	// the deep-link takes a modality override (`kind=audio|video` → the temporal viewers)
	// and an optional same-origin `media=` source (annotate a specific clip/fixture).
	if (browser) {
		const params = new URLSearchParams(window.location.search);
		const keys = params.get('keys');
		const rawKind = params.get('kind');
		const kind: MediaKind = rawKind === 'audio' || rawKind === 'video' ? rawKind : 'image';
		const rawMedia = params.get('media');
		const media = rawMedia?.startsWith('/') ? rawMedia : undefined; // same-origin only
		if (keys) reviewSelection.openKeys(keys.split(','), kind, media);
	}

	const unit = $derived(reviewSelection.active ?? DEMO_UNIT);
</script>

{#key unit.key}
	<AnnotatorShell {unit} />
{/key}
