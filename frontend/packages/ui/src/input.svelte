<script lang="ts">
	import { cn } from './utils';
	import type { HTMLInputAttributes } from 'svelte/elements';

	type Props = HTMLInputAttributes & { class?: string; value?: string };
	let { class: className, value = $bindable(''), ...rest }: Props = $props();
</script>

<input
	bind:value
	class={cn(
		'border-border bg-background flex h-8 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors',
		'placeholder:text-muted-foreground focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
		'disabled:cursor-not-allowed disabled:opacity-50',
		className,
	)}
	{...rest}
/>
