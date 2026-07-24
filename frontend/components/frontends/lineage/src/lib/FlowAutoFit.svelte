<script lang="ts">
	// Rendered INSIDE <SvelteFlow> so it can use the flow context (svelte-flow rule 5).
	// Re-frames the viewport whenever the node-set signature (`trigger`) changes — i.e. when nodes are
	// added/removed or the view switches — but NOT on every data poll, so it never fights a user pan/zoom.
	import { useSvelteFlow } from '@xyflow/svelte';
	import { tick } from 'svelte';

	let { trigger }: { trigger: string } = $props();
	const { fitView } = useSvelteFlow();

	$effect(() => {
		void trigger; // track the signature
		// maxZoom 1 = never scale a card ABOVE its natural size: a three-node estate used to be
		// blown up to fill the canvas, which read as "the graph is enormous".
		tick().then(() => fitView({ padding: 0.22, duration: 400, maxZoom: 1 }));
	});
</script>
