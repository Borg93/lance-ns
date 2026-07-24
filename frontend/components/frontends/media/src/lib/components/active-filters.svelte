<script lang="ts">
	import { activeView, type SearchSpec } from '@lance/api';
	import { X } from 'lucide-svelte';

	type Props = {
		spec: SearchSpec;
		onchange?: (spec: SearchSpec) => void;
	};
	let { spec = $bindable(), onchange }: Props = $props();

	/** Visible filter pills with X buttons. Used to fix the "filter stuck
      invisibly behind a popover" bug. Structured filter fields come from the
      descriptor (`filterFields`); their labels reuse the declared metadata
      labels, falling back to the field name. */
	type Pill =
		| { id: string; kind: 'filter'; field: string; label: string; value: string }
		| { id: string; kind: 'topic' | 'where'; label: string; value: string };
	const pills = $derived.by<Pill[]>(() => {
		const view = activeView();
		const labelFor = (field: string): string =>
			view.metadataFields.find((m) => m.field === field)?.label ?? field;
		const out: Pill[] = [];
		const filters = spec.filters ?? {};
		for (const field of view.filterFields) {
			const value = filters[field];
			if (value)
				out.push({ id: `filter:${field}`, kind: 'filter', field, label: labelFor(field), value });
		}
		if (spec.topic) out.push({ id: 'topic', kind: 'topic', label: 'Topic', value: spec.topic });
		if (spec.where) {
			const expr = spec.where.length > 48 ? `${spec.where.slice(0, 48)}…` : spec.where;
			out.push({ id: 'where', kind: 'where', label: 'SQL', value: expr });
		}
		return out;
	});

	function clear(pill: Pill) {
		if (pill.kind === 'topic') spec = { ...spec, topic: undefined };
		else if (pill.kind === 'where') spec = { ...spec, where: undefined };
		else if (pill.kind === 'filter') {
			const rest = { ...(spec.filters ?? {}) };
			delete rest[pill.field];
			spec = { ...spec, filters: Object.keys(rest).length > 0 ? rest : undefined };
		}
		onchange?.(spec);
	}

	function clearAll() {
		spec = { ...spec, filters: undefined, topic: undefined, where: undefined };
		onchange?.(spec);
	}
</script>

{#if pills.length}
	<div class="flex flex-wrap items-center gap-1.5 px-6 pb-3 text-[11px]">
		<span class="text-muted-foreground">Active filters:</span>
		{#each pills as p (p.id)}
			<span
				class="border-border bg-secondary flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium"
			>
				<span class="text-muted-foreground">{p.label}:</span>
				<span class="max-w-[280px] truncate">{p.value}</span>
				<button
					type="button"
					aria-label="Remove {p.label} filter"
					onclick={() => clear(p)}
					class="text-muted-foreground hover:text-destructive"
				>
					<X class="size-3" />
				</button>
			</span>
		{/each}
		{#if pills.length > 1}
			<button
				type="button"
				onclick={clearAll}
				class="text-muted-foreground hover:text-foreground ml-1"
			>
				Clear all
			</button>
		{/if}
	</div>
{/if}
