<script lang="ts">
	// A design-token-styled native select with the same API @lance/ui's Select exposed (value/options/
	// placeholder/ariaLabel), so the migrated apps/web components port by swapping only the import. Native
	// <select> keeps it accessible + dependency-light; a bits-ui listbox can replace it later if needed.
	interface Option {
		value: string;
		label: string;
	}

	let {
		value = $bindable(''),
		options,
		placeholder,
		ariaLabel,
		disabled = false,
	}: {
		value?: string;
		options: Option[];
		placeholder?: string;
		ariaLabel?: string;
		disabled?: boolean;
	} = $props();
</script>

<select
	bind:value
	aria-label={ariaLabel}
	{disabled}
	data-slot="select"
	class="border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50 h-8 rounded-md border px-2.5 text-sm focus-visible:ring-3 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
>
	{#if placeholder}
		<option value="" disabled>{placeholder}</option>
	{/if}
	{#each options as opt (opt.value)}
		<option value={opt.value}>{opt.label}</option>
	{/each}
</select>
