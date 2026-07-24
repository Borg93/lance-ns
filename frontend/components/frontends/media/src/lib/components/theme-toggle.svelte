<script lang="ts">
	import { browser } from '$app/environment';
	import { Button } from '@lance/ui';
	import { Sun, Moon } from 'lucide-svelte';

	// Self-contained: read the actual <html> class as truth, no external store.
	// Earlier attempts at a `theme.svelte.ts` module didn't reliably trigger
	// a re-render in production builds — keeping reactivity local to the
	// component side-steps that whole class of issues.
	let isDark = $state<boolean>(
		browser ? document.documentElement.classList.contains('dark') : false,
	);

	function toggle() {
		if (!browser) return;
		const next = !document.documentElement.classList.contains('dark');
		document.documentElement.classList.toggle('dark', next);
		isDark = next;
		try {
			localStorage.setItem('lance-media-theme', next ? 'dark' : 'light');
		} catch {
			/* private mode / disabled storage */
		}
	}
</script>

<Button
	variant="ghost"
	size="icon"
	title={isDark ? 'Switch to light' : 'Switch to dark'}
	aria-label="Toggle theme"
	onclick={toggle}
>
	{#if isDark}
		<Sun class="size-4" />
	{:else}
		<Moon class="size-4" />
	{/if}
</Button>
