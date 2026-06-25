<script lang="ts">
	import gsap from 'gsap';
	import type { RunStatus } from './types';

	let { runs }: { runs: RunStatus[] } = $props();

	const isRunning = (s?: string | null) => /START|RUNNING/i.test(s ?? '');
	const isFail = (s?: string | null) => /FAIL|ABORT/i.test(s ?? '');
	const color = (s?: string | null) =>
		isFail(s) ? 'var(--fail)' : s === 'COMPLETE' ? 'var(--ok)' : isRunning(s) ? '#ffc14d' : 'var(--mut)';

	function pct(r: RunStatus): number {
		if (r.state === 'COMPLETE') return 100;
		if (r.progress_total) return Math.round(((r.progress_done ?? 0) / r.progress_total) * 100);
		return isRunning(r.state) ? 8 : 0;
	}
	function label(r: RunStatus): string {
		if (r.state === 'COMPLETE') return 'COMPLETE';
		if (isFail(r.state)) return r.state ?? 'FAIL';
		if (isRunning(r.state)) return `RUNNING ${r.progress_done ?? 0}/${r.progress_total ?? 3}`;
		return r.state ?? '—';
	}
	const time = (s?: string | null) => (s ? new Date(s).toLocaleTimeString() : '');

	// gsap: animate the progress fill width to the current % whenever it changes.
	function fillWidth(node: HTMLElement, run: RunStatus) {
		gsap.to(node, { width: pct(run) + '%', duration: 0.5, ease: 'power2.out', overwrite: 'auto' });
	}
	// gsap: breathe the bar while the run is RUNNING; stop on terminal.
	function pulse(node: HTMLElement, run: RunStatus) {
		if (!isRunning(run.state)) {
			gsap.set(node, { opacity: 1 });
			return;
		}
		const tween = gsap.to(node, { opacity: 0.5, duration: 0.7, repeat: -1, yoyo: true, ease: 'sine.inOut' });
		return () => {
			tween.kill();
			gsap.set(node, { opacity: 1 });
		};
	}
	// gsap: slide each row in once on mount (no reactive reads -> runs once).
	function enter(node: HTMLElement) {
		gsap.from(node, { opacity: 0, y: 10, duration: 0.45, ease: 'power2.out' });
	}
</script>

<div class="board">
	{#if runs.length === 0}
		<p class="hint">No runs yet — trigger a step and watch them go <b>queued → running → done/failed</b>.</p>
	{/if}
	{#each runs as r (r.run_id)}
		<div class="row" class:fail={isFail(r.state)} {@attach enter}>
			<div class="top">
				<span class="job mono">{r.job}</span>
				<span class="pill" style:color={color(r.state)} style:border-color={color(r.state)}>{label(r)}</span>
			</div>
			<div class="track">
				<div
					class="fill"
					style:background={color(r.state)}
					{@attach (node) => fillWidth(node, r)}
					{@attach (node) => pulse(node, r)}
				></div>
			</div>
			<div class="meta">
				<span class="who">{r.author ?? '—'}{#if r.outputs.length} · → {r.outputs.join(', ')}{/if}</span>
				<span class="who">{time(r.updated_at)}</span>
			</div>
			{#if r.error_message}<div class="err">{r.error_message}</div>{/if}
		</div>
	{/each}
</div>

<style>
	.board {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.hint {
		color: var(--mut);
		font-size: 12px;
	}
	.hint b {
		color: var(--ink);
	}
	.row {
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 8px 10px;
	}
	.row.fail {
		border-color: var(--fail);
	}
	.top {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.job {
		font-size: 12px;
		color: var(--ink);
		font-weight: 600;
	}
	.pill {
		font-size: 10px;
		font-weight: 700;
		padding: 1px 7px;
		border-radius: 7px;
		border: 1px solid;
		white-space: nowrap;
	}
	.track {
		height: 6px;
		background: #0c1018;
		border-radius: 4px;
		overflow: hidden;
		margin: 7px 0 5px;
	}
	.fill {
		height: 100%;
		width: 0;
		border-radius: 4px;
	}
	.meta {
		display: flex;
		justify-content: space-between;
		gap: 8px;
	}
	.who {
		font-size: 11px;
		color: var(--mut);
	}
	.err {
		color: var(--fail);
		font-size: 11px;
		margin-top: 4px;
	}
</style>
