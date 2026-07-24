<script lang="ts" module>
	import { tv, type VariantProps } from 'tailwind-variants';

	export const sidebarMenuButtonVariants = tv({
		base: 'peer/menu-button ring-sidebar-ring hover:bg-sidebar-accent hover:text-sidebar-accent-foreground active:bg-sidebar-accent active:text-sidebar-accent-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-accent-foreground data-[active=true]:font-medium flex w-full items-center gap-2 overflow-hidden rounded-md p-2 text-left text-sm outline-hidden transition-[width,height,padding] focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50 group-data-[collapsible=icon]:size-8! group-data-[collapsible=icon]:p-2! [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0',
		variants: {
			variant: {
				default: 'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
				outline:
					'bg-background shadow-[0_0_0_1px_var(--sidebar-border)] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
			},
			size: {
				default: 'h-9 text-sm',
				sm: 'h-7 text-xs',
				lg: 'h-12 text-sm group-data-[collapsible=icon]:p-0!',
			},
		},
		defaultVariants: { variant: 'default', size: 'default' },
	});

	export type SidebarMenuButtonVariant = VariantProps<typeof sidebarMenuButtonVariants>['variant'];
	export type SidebarMenuButtonSize = VariantProps<typeof sidebarMenuButtonVariants>['size'];
</script>

<script lang="ts">
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import { cn, type WithElementRef } from '../utils';

	let {
		ref = $bindable(null),
		class: className,
		variant = 'default',
		size = 'default',
		isActive = false,
		tooltip,
		href = undefined,
		children,
		...restProps
	}: WithElementRef<HTMLButtonAttributes> &
		WithElementRef<HTMLAnchorAttributes> & {
			variant?: SidebarMenuButtonVariant;
			size?: SidebarMenuButtonSize;
			isActive?: boolean;
			/** native tooltip — useful when the rail is collapsed to icons */
			tooltip?: string;
		} = $props();
</script>

{#if href}
	<a
		bind:this={ref}
		data-slot="sidebar-menu-button"
		data-sidebar="menu-button"
		data-size={size}
		data-active={isActive}
		title={tooltip}
		{href}
		class={cn(sidebarMenuButtonVariants({ variant, size }), className)}
		{...restProps}
	>
		{@render children?.()}
	</a>
{:else}
	<button
		bind:this={ref}
		data-slot="sidebar-menu-button"
		data-sidebar="menu-button"
		data-size={size}
		data-active={isActive}
		title={tooltip}
		class={cn(sidebarMenuButtonVariants({ variant, size }), className)}
		{...restProps}
	>
		{@render children?.()}
	</button>
{/if}
