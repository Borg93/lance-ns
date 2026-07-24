<script lang="ts">
	import { Label } from 'bits-ui';
	import { cn } from './utils';
	import type { Snippet } from 'svelte';

	let {
		class: className,
		children,
		...rest
	}: { class?: string; children?: Snippet; for?: string } = $props();
</script>

<Label.Root
	data-slot="label"
	class={cn(
		'text-foreground text-xs font-medium select-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
		className,
	)}
	{...rest}
>
	{@render children?.()}
</Label.Root>
