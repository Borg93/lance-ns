<script lang="ts" module>
	export type SelectOption = { value: string; label: string };
</script>

<script lang="ts">
	import { Select } from 'bits-ui';
	import { cn } from './utils';
	import { Check, ChevronDown } from 'lucide-svelte';

	let {
		value = $bindable(''),
		options,
		placeholder = 'Select…',
		class: className,
		ariaLabel,
	}: {
		value?: string;
		options: SelectOption[];
		placeholder?: string;
		class?: string;
		ariaLabel?: string;
	} = $props();

	const selectedLabel = $derived(options.find((o) => o.value === value)?.label ?? '');
</script>

<Select.Root type="single" bind:value>
	<Select.Trigger
		aria-label={ariaLabel}
		data-slot="select-trigger"
		class={cn(
			'border-border bg-background flex h-8 w-full items-center justify-between gap-2 rounded-md border px-3 text-sm shadow-xs transition-colors',
			'hover:bg-muted focus-visible:ring-ring data-[state=open]:bg-muted focus-visible:ring-2 focus-visible:outline-none',
			className,
		)}
	>
		<span class={selectedLabel ? '' : 'text-muted-foreground'}>{selectedLabel || placeholder}</span>
		<ChevronDown class="size-4 opacity-60" />
	</Select.Trigger>
	<Select.Portal>
		<Select.Content
			sideOffset={6}
			class="border-border bg-card z-50 max-h-64 w-[var(--bits-floating-anchor-width)] min-w-[8rem] overflow-y-auto rounded-md border p-1 text-sm shadow-md"
		>
			<Select.Viewport>
				{#each options as opt (opt.value)}
					<Select.Item
						value={opt.value}
						label={opt.label}
						class="data-[highlighted]:bg-secondary/60 flex cursor-pointer items-center justify-between gap-2 rounded px-2 py-1.5 outline-none"
					>
						{#snippet children({ selected })}
							<span class={selected ? 'font-medium' : ''}>{opt.label}</span>
							{#if selected}<Check class="text-primary size-4" />{/if}
						{/snippet}
					</Select.Item>
				{/each}
			</Select.Viewport>
		</Select.Content>
	</Select.Portal>
</Select.Root>
