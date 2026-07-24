/**
 * The read→annotate bridge: a selection of media units to review, stepped through in
 * the annotator. The READ plane (atlas lasso / search) forms it — deep-linking to
 * `/annotator?keys=k1,k2,…` where each key is the descriptor key-path
 * (`doc/speech/chunk`) — and the annotator route opens it here + navigates. This is
 * the `Selection` bridge made concrete (see labeling/types.ts).
 */
import type { MediaKind, MediaUnit } from '$lib/viewer/types';

/** Build an annotator unit from a key-path (`doc/speech/chunk`) — the same path the
 *  chunk-frame + annotations endpoints take. Modality defaults to image/document (our
 *  corpus); `kind` selects the temporal viewers (audio waveform / video frame-overlay),
 *  whose media source defaults to the doc's `/api/media` stream — `mediaUrl` overrides
 *  it (a deep-link can annotate any same-origin media, e.g. a fixture clip). */
export function unitFromKey(key: string, kind: MediaKind = 'image', mediaUrl?: string): MediaUnit {
	const doc = key.split('/')[0];
	return {
		kind,
		key,
		imageUrl: `/api/chunk-frame/${key}`,
		...(kind === 'audio' || kind === 'video' ? { mediaUrl: mediaUrl ?? `/api/media/${doc}` } : {}),
		annotationsUrl: `/api/annotations/${key}`,
	};
}

class ReviewSelection {
	units = $state<MediaUnit[]>([]);
	index = $state(0);

	get active(): MediaUnit | null {
		return this.units[this.index] ?? null;
	}
	get total(): number {
		return this.units.length;
	}

	/** Open a selection of key-paths for review (from the read plane). `kind`/`mediaUrl`
	 *  apply to every unit (the deep-link's modality + media-source overrides). */
	openKeys(keys: string[], kind: MediaKind = 'image', mediaUrl?: string): void {
		this.units = keys.filter(Boolean).map((k) => unitFromKey(k, kind, mediaUrl));
		this.index = 0;
	}
	go(i: number): void {
		if (i >= 0 && i < this.units.length) this.index = i;
	}
	clear(): void {
		this.units = [];
		this.index = 0;
	}
}

/** Singleton — written by the read plane (via the route's `?keys=`), read by the
 *  annotator route + its PageNav. */
export const reviewSelection = new ReviewSelection();
