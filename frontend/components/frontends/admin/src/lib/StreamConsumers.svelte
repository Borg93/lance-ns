<script lang="ts">
	// One stream card's consumer rows on the shared @rask/ui DataTable (goal cond 4): sortable
	// columns, the same diagnostic hooks as before — pending/ack-pending pressure, redelivered as
	// the wedge signal (warn tone), and the >10-min stale chip judged against the MONITOR's clock
	// (`now`), never the browser's.
	import {
		createSvelteTable,
		DataTable,
		DataTableHeaderButton,
		getCoreRowModel,
		getPaginationRowModel,
		getSortedRowModel,
		renderComponent,
		renderSnippet,
		type ColumnDef,
		type PaginationState,
		type SortingState,
	} from '@rask/ui/data-table';
	import type { JetStreamConsumer } from './jetstream';

	let { consumers, now }: { consumers: JetStreamConsumer[]; now: string } = $props();

	// A consumer whose last delivery activity is >10 min behind the monitor's own clock is stale:
	// on an active fabric that usually means its app stopped reading (wedged subscriber).
	const STALE_MS = 10 * 60 * 1000;
	function isStale(lastActive: string | undefined): boolean {
		if (!lastActive) return false;
		const active = new Date(lastActive).getTime();
		const ref = new Date(now).getTime();
		return !Number.isNaN(active) && !Number.isNaN(ref) && ref - active > STALE_MS;
	}
	function when(ts: string | undefined): string {
		if (!ts) return '—';
		const d = new Date(ts);
		return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
	}

	let sorting = $state<SortingState>([]);
	let pagination = $state<PaginationState>({ pageIndex: 0, pageSize: 10 });

	const sortableHeader =
		(label: string) =>
		({
			column,
		}: {
			column: {
				getIsSorted(): false | 'asc' | 'desc';
				getToggleSortingHandler(): ((e: Event) => void) | undefined;
			};
		}) =>
			renderComponent(DataTableHeaderButton, {
				label,
				sorted: column.getIsSorted(),
				onclick: column.getToggleSortingHandler(),
			});

	const columns: ColumnDef<JetStreamConsumer>[] = [
		{
			id: 'service',
			accessorKey: 'service',
			header: sortableHeader('service'),
			cell: ({ row }) => renderSnippet(serviceCell, row.original),
		},
		{
			id: 'consumer',
			accessorKey: 'name',
			header: sortableHeader('consumer'),
			cell: ({ row }) => renderSnippet(consumerCell, row.original),
		},
		{
			id: 'pending',
			accessorKey: 'num_pending',
			header: sortableHeader('pending'),
			cell: ({ row }) => renderSnippet(numCell, { n: row.original.num_pending, warn: false }),
			meta: { headerClass: 'w-24 text-right', cellClass: 'text-right' },
		},
		{
			id: 'ack-pending',
			accessorKey: 'num_ack_pending',
			header: sortableHeader('ack-pending'),
			cell: ({ row }) => renderSnippet(numCell, { n: row.original.num_ack_pending, warn: false }),
			meta: { headerClass: 'w-28 text-right', cellClass: 'text-right' },
		},
		{
			id: 'redelivered',
			accessorKey: 'num_redelivered',
			header: sortableHeader('redelivered'),
			cell: ({ row }) => renderSnippet(numCell, { n: row.original.num_redelivered, warn: true }),
			meta: { headerClass: 'w-28 text-right', cellClass: 'text-right' },
		},
		{
			id: 'last-active',
			accessorFn: (c) => c.last_active ?? '',
			header: sortableHeader('last active'),
			cell: ({ row }) => renderSnippet(activeCell, row.original),
			meta: { cellClass: 'whitespace-nowrap' },
		},
	];

	const table = createSvelteTable({
		get data() {
			return consumers;
		},
		columns,
		state: {
			get sorting() {
				return sorting;
			},
			get pagination() {
				return pagination;
			},
		},
		onSortingChange: (u) => (sorting = typeof u === 'function' ? u(sorting) : u),
		onPaginationChange: (u) => (pagination = typeof u === 'function' ? u(pagination) : u),
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getPaginationRowModel: getPaginationRowModel(),
	});
</script>

{#snippet serviceCell(c: JetStreamConsumer)}
	<span class="service mono" class:stale={isStale(c.last_active)}>{c.service}</span>
{/snippet}
{#snippet consumerCell(c: JetStreamConsumer)}
	<span class="mono" class:stale={isStale(c.last_active)}>
		{c.durable ? c.name : `${c.name} (ephemeral)`}
	</span>
{/snippet}
{#snippet numCell({ n, warn }: { n: number; warn: boolean })}
	<span class="num mono" class:pend={!warn && n > 0} class:warn={warn && n > 0}>{n}</span>
{/snippet}
{#snippet activeCell(c: JetStreamConsumer)}
	<span class="faint mono" class:stale={isStale(c.last_active)}>
		{when(c.last_active)}
		{#if isStale(c.last_active)}
			<span class="stalechip" title="No delivery activity for over 10 minutes">stale</span>
		{/if}
	</span>
{/snippet}

<DataTable {table} emptyMessage="No consumers bound." />

<style>
	.service {
		color: var(--ink);
	}
	.num {
		color: var(--faint);
	}
	.pend {
		color: var(--mut);
	}
	.warn {
		color: var(--warn, #d18b28);
	}
	/* Stale consumer: dimmed cells (still legible) + a warn-toned chip on the last-active cell. */
	.stale {
		opacity: 0.55;
	}
	.stalechip {
		display: inline-block;
		border: 1px solid color-mix(in srgb, var(--warn, #d18b28) 60%, var(--line));
		border-radius: var(--radius-sm);
		color: var(--warn, #d18b28);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0 5px;
		margin-left: 6px;
		opacity: 1;
	}
	.faint {
		color: var(--faint);
		white-space: nowrap;
	}
	.mono {
		font-family: ui-monospace, monospace;
	}
</style>
