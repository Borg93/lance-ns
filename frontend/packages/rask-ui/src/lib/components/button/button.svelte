<script lang="ts">
	import type { Snippet } from 'svelte';

	type Variant = 'default' | 'ghost' | 'outline';

	let {
		href,
		variant = 'default',
		children,
	}: { href?: string; variant?: Variant; children: Snippet } = $props();

	const base =
		'inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors';
	const variants: Record<Variant, string> = {
		default: 'bg-primary text-primary-foreground hover:bg-primary/90',
		ghost: 'hover:bg-accent hover:text-accent-foreground',
		outline: 'border-input hover:bg-accent border',
	};
</script>

{#if href}
	<a {href} class="{base} {variants[variant]}">{@render children()}</a>
{:else}
	<button type="button" class="{base} {variants[variant]}">{@render children()}</button>
{/if}
