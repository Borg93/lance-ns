<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn, type WithElementRef } from '../utils';
	import { setSidebar } from './context.svelte.js';
	import {
		SIDEBAR_COOKIE_MAX_AGE,
		SIDEBAR_COOKIE_NAME,
		SIDEBAR_KEYBOARD_SHORTCUT,
		SIDEBAR_WIDTH,
		SIDEBAR_WIDTH_ICON,
	} from './constants.js';

	let {
		ref = $bindable(null),
		open = $bindable(true),
		onOpenChange = () => {},
		class: className,
		style,
		children,
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLDivElement>> & {
		open?: boolean;
		onOpenChange?: (open: boolean) => void;
	} = $props();

	const sidebar = setSidebar({
		open: () => open,
		setOpen: (value: boolean) => {
			open = value;
			onOpenChange(value);
			// persist across reloads (read back in the layout on boot)
			document.cookie = `${SIDEBAR_COOKIE_NAME}=${open}; path=/; max-age=${SIDEBAR_COOKIE_MAX_AGE}`;
		},
	});

	function handleShortcut(e: KeyboardEvent) {
		if (e.key === SIDEBAR_KEYBOARD_SHORTCUT && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			sidebar.toggle();
		}
	}
</script>

<svelte:window onkeydown={handleShortcut} />

<div
	bind:this={ref}
	data-slot="sidebar-wrapper"
	style="--sidebar-width: {SIDEBAR_WIDTH}; --sidebar-width-icon: {SIDEBAR_WIDTH_ICON}; {style ??
		''}"
	class={cn('group/sidebar-wrapper text-sidebar-foreground flex min-h-svh w-full', className)}
	{...restProps}
>
	{@render children?.()}
</div>
