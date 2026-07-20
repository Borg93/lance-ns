<script lang="ts">
	// Shared single-select built on the bits-ui headless primitive — the app's one styled dropdown, so a
	// native <select> is never hand-rolled per form. Keyboard nav, typeahead, focus + portal positioning
	// come from bits-ui; the CSS-var styling matches the rest of the console. Options are flat {value,label}.
	import { Check, ChevronDown } from "@lucide/svelte";
	import { Select } from "bits-ui";

	type Option = { value: string; label: string; disabled?: boolean };

	let {
		value = $bindable(""),
		options,
		placeholder = "Select…",
		ariaLabel = undefined,
		disabled = false,
	}: {
		value?: string;
		options: Option[];
		placeholder?: string;
		ariaLabel?: string;
		disabled?: boolean;
	} = $props();

	const label = $derived(options.find((o) => o.value === value)?.label ?? placeholder);
</script>

<Select.Root type="single" bind:value items={options} {disabled}>
	<Select.Trigger class="lui-sel-trigger" aria-label={ariaLabel}>
		<span class:lui-sel-ph={!value}>{label}</span>
		<ChevronDown size={13} />
	</Select.Trigger>
	<Select.Portal>
		<Select.Content class="lui-sel-content" sideOffset={4}>
			<Select.Viewport>
				{#each options as o (o.value)}
					<Select.Item class="lui-sel-item" value={o.value} label={o.label} disabled={o.disabled}>
						{#snippet children({ selected }: { selected: boolean })}
							<span>{o.label}</span>
							{#if selected}<Check size={13} />{/if}
						{/snippet}
					</Select.Item>
				{/each}
			</Select.Viewport>
		</Select.Content>
	</Select.Portal>
</Select.Root>

<style>
	/* bits-ui renders its own elements with the classes passed above, so they are styled globally
	   (namespaced `lui-sel-*` to avoid collisions) rather than through scoped selectors. */
	:global(.lui-sel-trigger) {
		display: inline-flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		min-width: 120px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm, 6px);
		color: var(--ink);
		font: inherit;
		font-size: 12px;
		padding: 4px 9px;
		cursor: pointer;
	}
	:global(.lui-sel-trigger:hover) {
		background: var(--panel);
	}
	:global(.lui-sel-trigger[data-disabled]) {
		opacity: 0.5;
		cursor: default;
	}
	:global(.lui-sel-ph) {
		color: var(--faint);
	}
	:global(.lui-sel-content) {
		z-index: 60;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm, 6px);
		padding: 4px;
		box-shadow: 0 6px 20px rgb(0 0 0 / 0.25);
		max-height: 260px;
		overflow-y: auto;
	}
	:global(.lui-sel-item) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		font-size: 12px;
		color: var(--ink);
		padding: 4px 8px;
		border-radius: var(--radius-sm, 6px);
		cursor: pointer;
		user-select: none;
	}
	:global(.lui-sel-item[data-highlighted]) {
		background: var(--panel-2);
	}
	:global(.lui-sel-item[data-disabled]) {
		opacity: 0.4;
		cursor: default;
	}
</style>
