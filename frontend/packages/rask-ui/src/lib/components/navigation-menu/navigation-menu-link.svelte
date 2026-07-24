<script lang="ts">
	import { NavigationMenu as NavigationMenuPrimitive } from 'bits-ui';
	import { cn } from '../../utils/index.js';

	let {
		ref = $bindable(null),
		class: className,
		...restProps
	}: NavigationMenuPrimitive.LinkProps = $props();
</script>

<NavigationMenuPrimitive.Link
	bind:ref
	data-slot="navigation-menu-link"
	class={cn(
		"data-[active=true]:bg-muted data-[active=true]:text-foreground data-[active=true]:hover:bg-muted data-[active=true]:focus:bg-muted hover:bg-muted hover:text-foreground focus:bg-muted focus:text-foreground focus-visible:border-ring focus-visible:ring-ring/50 [&_svg:not([class*='text-'])]:text-muted-foreground flex flex-col gap-1 rounded-md border border-transparent p-2 text-sm transition-colors outline-none focus-visible:ring-3 [&_svg:not([class*='size-'])]:size-4",
		className,
	)}
	{...restProps}
/>
