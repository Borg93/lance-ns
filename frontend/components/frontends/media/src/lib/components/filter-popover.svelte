<script lang="ts">
	import { Input, Button, type SelectOption } from '@lance/ui';
	import { Popover } from 'bits-ui';
	import { activeView, listColumns, type SearchSpec, type ColumnInfo } from '@lance/api';
	import { Filter, X, Eye, EyeOff, Plus } from 'lucide-svelte';
	import { cn } from '$lib/utils';

	type Props = {
		spec: SearchSpec;
		onchange?: () => void;
	};
	let { spec = $bindable(), onchange }: Props = $props();

	// All filters go through the generic column builder below, which compiles to
	// a `where` clause — no hardcoded per-corpus quick filters.
	//
	// Writable $derived: re-syncs from `spec` when it changes OUTSIDE this popover
	// — an active-filter pill removed (active-filters.svelte), a topic seeded, or
	// Clear-all — fixing the not-dropped-when-popped bug a mount-time snapshot
	// had. Typing in the raw-SQL box is NOT clobbered: it reassigns `whereSql`
	// locally (allowed on a writable derived) and only an external `spec.where`
	// change recomputes it.
	let whereSql = $derived(spec.where ?? '');

	function commit() {
		// Always prefilter (correct + uses the scalar index; never returns < n).
		spec = { ...spec, where: whereSql || undefined };
		onchange?.();
	}

	function clearAll() {
		whereSql = '';
		commit();
	}

	const activeCount = $derived(whereSql.trim() ? 1 : 0);

	// Example WHERE for the raw-SQL box: a real filterable field where one is
	// declared, else a generic numeric comparison — never a hardcoded corpus name.
	const wherePlaceholder = $derived.by(() => {
		const fields = activeView().filterFields;
		return fields.length > 0 ? `${fields[0]} LIKE '%…%'` : 'duration > 60';
	});

	// ── Filterable columns (from the backend) ──────────────────────────────
	let columns = $state<ColumnInfo[]>([]);
	let columnsState = $state<'loading' | 'ready' | 'error'>('loading');
	$effect(() => {
		listColumns()
			.then((c) => {
				columns = c;
				columnsState = 'ready';
			})
			.catch(() => {
				columns = [];
				columnsState = 'error';
			});
	});

	// Per-column hide, persisted so a decluttered list survives reloads.
	const HIDE_KEY = 'lance-media-hidden-cols';
	let hidden = $state<Set<string>>(new Set());
	$effect(() => {
		try {
			const v = localStorage.getItem(HIDE_KEY);
			if (v) hidden = new Set(JSON.parse(v) as string[]);
		} catch {
			/* ignore */
		}
	});
	function toggleHide(name: string) {
		const next = new Set(hidden);
		if (next.has(name)) next.delete(name);
		else next.add(name);
		hidden = next;
		try {
			localStorage.setItem(HIDE_KEY, JSON.stringify([...next]));
		} catch {
			/* ignore */
		}
	}

	const visibleCols = $derived(columns.filter((c) => !hidden.has(c.name)));

	// ── Filter builder: column · operator · value → predicate → WHERE ──────
	const NUMBER_OPS: SelectOption[] = [
		{ value: '=', label: '=' },
		{ value: '!=', label: '≠' },
		{ value: '>', label: '>' },
		{ value: '>=', label: '≥' },
		{ value: '<', label: '<' },
		{ value: '<=', label: '≤' },
	];
	const TEXT_OPS: SelectOption[] = [
		{ value: 'contains', label: 'contains' },
		{ value: 'equals', label: 'equals' },
		{ value: 'starts', label: 'starts with' },
	];
	const BOOL_OPS: SelectOption[] = [
		{ value: '=', label: 'is' },
		{ value: '!=', label: 'is not' },
	];

	let colName = $state('');
	let op = $state('contains');
	let val = $state('');

	// `type` is the backend's Lance-derived kind (number | time | boolean | text);
	// ops follow the KIND, not any column name — comparison ops for number/time, a
	// true/false toggle for boolean, substring/exact for text.
	const colType = $derived(columns.find((c) => c.name === colName)?.type ?? 'text');
	const opOptions = $derived(
		colType === 'number' || colType === 'time'
			? NUMBER_OPS
			: colType === 'boolean'
				? BOOL_OPS
				: TEXT_OPS,
	);
	// Keep the operator valid when the column type changes.
	$effect(() => {
		const first = opOptions[0];
		if (first && !opOptions.some((o) => o.value === op)) op = first.value;
	});

	function buildClause(): string | null {
		if (!colName || !val.trim()) return null;
		const v = val.trim();
		if (colType === 'number') {
			const num = Number(v);
			if (Number.isNaN(num)) return null;
			return `${colName} ${op} ${num}`;
		}
		if (colType === 'boolean') {
			const t = v.toLowerCase();
			const b = ['true', '1', 'yes', 'y'].includes(t)
				? 'true'
				: ['false', '0', 'no', 'n'].includes(t)
					? 'false'
					: null;
			return b === null ? null : `${colName} ${op} ${b}`;
		}
		const esc = v.replace(/'/g, "''");
		// Temporal: comparison ops (NUMBER_OPS) against a quoted date/timestamp literal.
		if (colType === 'time') return `${colName} ${op} '${esc}'`;
		if (op === 'equals') return `${colName} = '${esc}'`;
		if (op === 'starts') return `${colName} LIKE '${esc}%'`;
		return `${colName} LIKE '%${esc}%'`;
	}

	function addFilter() {
		const clause = buildClause();
		if (!clause) return;
		whereSql = whereSql.trim() ? `${whereSql.trim()} AND ${clause}` : clause;
		val = '';
		commit(); // ← runs the search immediately so results visibly update
	}

	let manageOpen = $state(false);
</script>

<Popover.Root>
	<Popover.Trigger
		class={cn(
			'border-border bg-background inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs transition-colors',
			activeCount > 0 ? 'text-foreground' : 'text-muted-foreground',
			'hover:bg-muted hover:text-foreground data-[state=open]:bg-muted data-[state=open]:text-foreground',
		)}
		title="Filter results by any column"
	>
		<Filter class="size-3.5" />
		<span>Filters</span>
		{#if activeCount > 0}
			<span
				class="bg-primary text-primary-foreground ml-1 rounded-full px-1.5 text-[10px] font-bold"
			>
				{activeCount}
			</span>
		{/if}
	</Popover.Trigger>

	<Popover.Portal>
		<Popover.Content
			sideOffset={6}
			align="end"
			class="border-border bg-card z-50 flex max-h-[75vh] w-[340px] flex-col gap-3 overflow-y-auto rounded-md border p-3 text-xs shadow-md"
		>
			<div class="flex items-center">
				<span class="text-muted-foreground text-[11px] font-semibold tracking-wider uppercase">
					Filter results
				</span>
				{#if activeCount > 0}
					<button
						type="button"
						onclick={clearAll}
						class="text-muted-foreground hover:text-foreground ml-auto flex items-center gap-0.5 text-[11px]"
					>
						<X class="size-3" /> Clear
					</button>
				{/if}
			</div>

			<!-- Builder: column · operator · value → Add -->
			<div class="flex flex-col gap-1.5">
				<span class="text-muted-foreground">Add a filter</span>
				<div class="flex gap-1.5">
					<select
						bind:value={colName}
						aria-label="Column"
						class="border-border bg-background text-foreground focus-visible:ring-ring h-8 flex-1 rounded-md border px-2 text-xs focus-visible:ring-2 focus-visible:outline-none"
					>
						<option value="" disabled>Column…</option>
						{#each visibleCols as c (c.name)}
							<option value={c.name}>{c.name} · {c.type}</option>
						{/each}
					</select>
					<select
						bind:value={op}
						aria-label="Operator"
						class="border-border bg-background text-foreground focus-visible:ring-ring h-8 w-28 rounded-md border px-2 text-xs focus-visible:ring-2 focus-visible:outline-none"
					>
						{#each opOptions as o (o.value)}
							<option value={o.value}>{o.label}</option>
						{/each}
					</select>
				</div>
				<div class="flex gap-1.5">
					<Input
						bind:value={val}
						placeholder={colType === 'number'
							? 'number…'
							: colType === 'time'
								? 'date/time…'
								: colType === 'boolean'
									? 'true / false'
									: 'value…'}
						class="h-8 flex-1 text-xs"
						onkeydown={(e) => {
							if (e.key === 'Enter') {
								e.preventDefault();
								addFilter();
							}
						}}
					/>
					<Button
						type="button"
						size="default"
						disabled={!colName || !val.trim()}
						onclick={addFilter}
					>
						<Plus class="size-4" /> Add
					</Button>
				</div>
				<span class="text-muted-foreground/70 text-[10px]">
					Pick a column, an operator, a value, then Add — the search re-runs immediately.
				</span>
				{#if columnsState === 'error'}
					<span class="text-destructive text-[10px]">
						Couldn't load columns — is the backend running?
					</span>
				{/if}
			</div>

			<!-- Manage which columns appear in the builder -->
			<div class="border-border border-t pt-2">
				<button
					type="button"
					onclick={() => (manageOpen = !manageOpen)}
					class="text-muted-foreground hover:text-foreground flex w-full items-center justify-between text-[11px]"
				>
					<span>Manage columns ({visibleCols.length}/{columns.length} shown)</span>
					<span class="text-[10px]">{manageOpen ? 'hide' : 'show'}</span>
				</button>
				{#if manageOpen}
					<div class="mt-1.5 flex flex-wrap gap-1">
						{#each columns as c (c.name)}
							{@const isHidden = hidden.has(c.name)}
							<button
								type="button"
								onclick={() => toggleHide(c.name)}
								title={isHidden ? `Show '${c.name}'` : `Hide '${c.name}'`}
								class={cn(
									'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] transition-colors',
									isHidden
										? 'border-border text-muted-foreground/60 hover:text-foreground border-dashed'
										: 'border-border text-foreground hover:bg-muted',
								)}
							>
								{#if isHidden}<EyeOff class="size-3" />{:else}<Eye class="size-3" />{/if}
								{c.name}
							</button>
						{/each}
						{#if columnsState === 'loading'}
							<span class="text-muted-foreground text-[11px]">Loading columns…</span>
						{:else if columnsState === 'error'}
							<span class="text-destructive text-[11px]">
								Couldn't load columns — is the backend running?
							</span>
						{:else if columns.length === 0}
							<span class="text-muted-foreground text-[11px]">No filterable columns.</span>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Advanced raw SQL escape hatch -->
			<details class="border-border border-t pt-2">
				<summary class="text-muted-foreground hover:text-foreground cursor-pointer text-[11px]">
					Advanced — raw SQL (WHERE)
				</summary>
				<textarea
					bind:value={whereSql}
					onchange={commit}
					onblur={commit}
					rows={2}
					placeholder={wherePlaceholder}
					class="border-border bg-background text-foreground placeholder:text-muted-foreground/70 focus-visible:ring-ring mt-1.5 min-h-[2rem] w-full resize-y rounded-md border px-2 py-1.5 font-mono text-[11px] focus-visible:ring-2 focus-visible:outline-none"
				></textarea>
				<span class="text-muted-foreground/70 text-[10px]">
					The builder above writes here. Edit directly for OR / parentheses / functions.
				</span>
			</details>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
