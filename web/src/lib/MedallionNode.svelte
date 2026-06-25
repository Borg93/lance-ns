<script lang="ts" module>
	import type { Node, NodeProps } from '@xyflow/svelte';

	export type MedallionData = {
		id: string;
		layer: number;
		source_uri?: string | null;
		tags: string[];
		versions: string[];
		failed: boolean;
		selected: boolean;
		runState?: string | null;
	};
	export type MedallionNodeType = Node<MedallionData, 'medallion'>;

	const COLORS = ['#ff9457', '#cd7f32', '#9fb6cf', '#ffc14d', '#8aa0bd'];
</script>

<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { pulse, pop } from './attachments';

	let { data }: NodeProps<MedallionNodeType> = $props();

	const color = $derived(COLORS[data.layer] ?? COLORS[4]);
	// Derived *primitives* so the continuous pulse only re-inits when the value actually flips,
	// not on every 2s poll (which reassigns `data`).
	const running = $derived(/START|RUNNING/i.test(data.runState ?? ''));
	const done = $derived(data.runState === 'COMPLETE');
	const failedRun = $derived(/FAIL|ABORT/i.test(data.runState ?? ''));
	const stateKey = $derived(data.runState ?? '');
	const ring = $derived(failedRun ? 'var(--fail)' : done ? 'var(--ok)' : running ? 'var(--amber)' : color);
</script>

<div
	class="node"
	class:selected={data.selected}
	style:--accent={color}
	style:--ring={ring}
	{@attach pop(stateKey)}
	{@attach pulse(running, '255, 193, 77')}
>
	<Handle type="target" position={Position.Left} />
	<div class="bar"></div>
	<div class="body">
		<div class="name">{data.id}</div>
		<div class="uri">{data.source_uri ?? '(pending)'}</div>
		<div class="chips">
			{#each data.versions as v (v)}
				<span class="chip ok">v{v}</span>
			{/each}
			{#if data.failed}
				<span class="chip fail">⚠ failed</span>
			{/if}
			{#each data.tags as t (t)}
				<span class="chip tag">{t}</span>
			{/each}
		</div>
	</div>
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.node {
		display: flex;
		width: 220px;
		border: 1.5px solid var(--ring, var(--accent));
		border-radius: var(--radius);
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		overflow: hidden;
		font-family: ui-sans-serif, system-ui, sans-serif;
		box-shadow: var(--shadow);
		transition: border-color 0.35s var(--ease);
	}
	.node.selected {
		outline: 2px solid #46f9b8;
		outline-offset: 2px;
	}
	.bar {
		width: 6px;
		background: var(--accent);
	}
	.body {
		padding: 8px 10px;
		min-width: 0;
	}
	.name {
		font-weight: 600;
		font-size: 13px;
		color: var(--ink);
	}
	.uri {
		font-size: 10.5px;
		color: var(--mut);
		margin: 2px 0 6px;
		word-break: break-all;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.chip {
		font-size: 10px;
		font-weight: 700;
		padding: 1px 7px;
		border-radius: 999px;
	}
	.chip.ok {
		background: var(--ok);
		color: #06210f;
	}
	.chip.fail {
		background: var(--fail);
		color: #2a0307;
	}
	.chip.tag {
		background: #243245;
		color: #aebfd6;
		font-weight: 600;
	}
</style>
