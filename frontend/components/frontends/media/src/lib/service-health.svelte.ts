/**
 * Live service health, polled once for the whole zone.
 *
 * The backend already tells us which encoders are reachable — `/api/health` reports `embed.ok` and
 * `rerank.ok`. Nothing was reading it except the sidebar's status dot, so the search bar happily offered
 * Meaning and Hybrid modes on a deployment where neither can run: measured 2026-07-26 through the ingress,
 * `mode=fts` → 200 with rows, `mode=semantic` and `mode=hybrid` → 503 "embed …", because the viewer's
 * `embed_url` still defaults to `http://127.0.0.1:8001` (lance-media's sidecar-era default) and the chart
 * never re-pointed it. A user picked a mode, got a failure toast, and learned nothing about why. The one
 * signal was a red dot in a corner — permanently red, so ignorable.
 *
 * Driven by HEALTH rather than a build-time flag on purpose: the moment an encoder is deployed and
 * `embed.ok` flips true, the modes light up on the next poll with nothing to remember to change. A flag
 * would have to be found and flipped by whoever deploys the encoder, which is how a capability stays
 * hidden after it starts working.
 *
 * One store, one poll: the sidebar badge and the mode selector read the same object, so they cannot
 * disagree about whether search works — two independent fetches would eventually show a green dot beside a
 * disabled mode.
 */
import { getHealth, type Health } from '@repo/media-api';

const POLL_MS = 10_000;

class ServiceHealth {
	/** The last successful reading; `null` before the first, or after the backend became unreachable. */
	current = $state<Health | null>(null);
	/** The last fetch error, for the badge to show. `null` while healthy. */
	error = $state<string | null>(null);
	#refs = 0;
	#timer: ReturnType<typeof setInterval> | null = null;

	async refresh(): Promise<void> {
		try {
			this.current = await getHealth();
			this.error = null;
		} catch (e) {
			this.error = e instanceof Error ? e.message : 'fetch failed';
			this.current = null;
		}
	}

	/** Start polling while at least one component wants it; stop when the last one goes away.
	 *  Ref-counted because both the sidebar badge and the search bar subscribe, and the first to unmount
	 *  must not stop the poll the other still depends on. Call from an `$effect` and return the result. */
	subscribe(): () => void {
		this.#refs += 1;
		if (this.#timer === null) {
			void this.refresh();
			this.#timer = setInterval(() => void this.refresh(), POLL_MS);
		}
		return () => {
			this.#refs -= 1;
			if (this.#refs <= 0 && this.#timer !== null) {
				clearInterval(this.#timer);
				this.#timer = null;
			}
		};
	}

	/** Can a query be turned into a vector? Meaning and Hybrid both need this.
	 *
	 *  `true` before the first reading lands, deliberately: a mode that flickers disabled on every page load
	 *  is worse than one that fails honestly with a 503, and the 503 already says why. Only a reading that
	 *  actually says `ok: false` disables anything. */
	get canEmbed(): boolean {
		return this.current === null ? true : this.current.embed.ok !== false;
	}

	/** Can results be re-scored? The Rerank toggle needs this. */
	get canRerank(): boolean {
		return this.current === null ? true : this.current.rerank.ok !== false;
	}

	/** Why a capability is unavailable, for a tooltip — the backend's own error, not a guess. */
	get embedReason(): string | null {
		if (this.canEmbed) return null;
		const url = this.current?.embed.url ?? 'the embedding service';
		return `No embedding service reachable at ${url}, so a query cannot be turned into a vector.`;
	}

	get rerankReason(): string | null {
		if (this.canRerank) return null;
		const url = this.current?.rerank.url ?? 'the rerank service';
		return `No rerank service reachable at ${url}.`;
	}
}

export const serviceHealth = new ServiceHealth();
