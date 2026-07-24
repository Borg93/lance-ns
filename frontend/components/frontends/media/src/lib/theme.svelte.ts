import { browser } from '$app/environment';

/**
 * Reactive app color mode — tracks the `.dark` class on `<html>` (toggled by the
 * theme button) so consumers update LIVE instead of reading it once at mount.
 *
 * Call once at component init (it registers a `$effect` that observes the class)
 * and read `.current` / `.isDark`. Returns `'dark' | 'light'` (no framework
 * coupling) so both the Svelte Flow canvas and the WebGPU atlas can share it.
 */
export function useColorMode(): { readonly current: 'dark' | 'light'; readonly isDark: boolean } {
	let isDark = $state(browser && document.documentElement.classList.contains('dark'));

	$effect(() => {
		const html = document.documentElement;
		const sync = () => (isDark = html.classList.contains('dark'));
		const observer = new MutationObserver(sync);
		observer.observe(html, { attributes: true, attributeFilter: ['class'] });
		sync(); // catch any change between the initial read and the effect mounting
		return () => observer.disconnect();
	});

	return {
		get current() {
			return isDark ? 'dark' : 'light';
		},
		get isDark() {
			return isDark;
		},
	};
}
