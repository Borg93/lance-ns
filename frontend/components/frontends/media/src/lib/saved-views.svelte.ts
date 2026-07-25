/**
 * Reactive saved-views store — named read-plane selections persisted to localStorage.
 * Thin runes wrapper over the pure logic in saved-views.ts.
 */
import { browser } from '$app/environment';
import type { SearchSpec } from '@lance/media-api';
import {
	removeView,
	stripEphemeral,
	upsertView,
	viewsForDataset,
	type SavedView,
} from '$lib/saved-views';

const KEY = 'lance-media:saved-views';

function load(): SavedView[] {
	if (!browser) return [];
	try {
		const raw = localStorage.getItem(KEY);
		const parsed: unknown = raw ? JSON.parse(raw) : [];
		// Guard SHAPE, not just JSON validity: a stored 'null'/'{}'/'42' parses fine but
		// would make `views` a non-array → a .filter crash on first render.
		return Array.isArray(parsed) ? (parsed as SavedView[]) : [];
	} catch {
		return [];
	}
}

class SavedViewsStore {
	views = $state<SavedView[]>(load());

	forDataset(dataset: string): SavedView[] {
		return viewsForDataset(this.views, dataset);
	}

	/** Save (or overwrite) a named view of the current spec for a dataset. */
	save(name: string, spec: SearchSpec, dataset: string): void {
		const trimmed = name.trim();
		if (!trimmed) return;
		this.views = upsertView(this.views, { name: trimmed, dataset, spec: stripEphemeral(spec) });
		this._persist();
	}

	remove(name: string, dataset: string): void {
		this.views = removeView(this.views, name, dataset);
		this._persist();
	}

	private _persist(): void {
		if (!browser) return;
		try {
			localStorage.setItem(KEY, JSON.stringify(this.views));
		} catch {
			/* storage full / disabled — views stay in-memory this session */
		}
	}
}

export const savedViews = new SavedViewsStore();
