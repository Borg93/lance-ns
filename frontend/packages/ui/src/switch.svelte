<script lang="ts">
	import { Switch } from 'bits-ui';
	import { cn } from './utils';

	let {
		checked = $bindable(false),
		class: className,
		...rest
	}: { checked?: boolean; class?: string; 'aria-label'?: string } = $props();
</script>

<Switch.Root
	bind:checked
	data-slot="switch"
	class={cn(
		'inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors',
		'focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
		'data-[state=checked]:bg-primary data-[state=unchecked]:bg-secondary',
		className,
	)}
	{...rest}
>
	<Switch.Thumb
		class="bg-background pointer-events-none block size-4 rounded-full shadow transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5"
	/>
</Switch.Root>
