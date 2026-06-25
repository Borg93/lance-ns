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
	};
	export type MedallionNodeType = Node<MedallionData, 'medallion'>;

	const COLORS = ['#ff9457', '#cd7f32', '#9fb6cf', '#ffc14d', '#8aa0bd'];
</script>

<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data }: NodeProps<MedallionNodeType> = $props();
	const color = $derived(COLORS[data.layer] ?? COLORS[4]);
</script>

<div class="node" class:selected={data.selected} style:--accent={color}>
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
		border: 1.5px solid var(--accent);
		border-radius: 10px;
		background: #141b27;
		overflow: hidden;
		font-family: ui-sans-serif, system-ui, sans-serif;
	}
	.node.selected {
		box-shadow: 0 0 0 2px #46f9b8;
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
		color: #e6edf6;
	}
	.uri {
		font-size: 10.5px;
		color: #8aa0bd;
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
		border-radius: 7px;
	}
	.chip.ok {
		background: #46f9b8;
		color: #06210f;
	}
	.chip.fail {
		background: #ff5d6c;
		color: #2a0307;
	}
	.chip.tag {
		background: #243245;
		color: #aebfd6;
		font-weight: 600;
	}
</style>
