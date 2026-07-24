<script lang="ts">
	// `/audit` — the #77 admin audit-log viewer over the #41 compliance trail. Events land on the dedicated
	// `lance.audit` logger → OTLP → GreptimeDB (`opentelemetry_logs`); the /api/audit BFF queries them
	// server-side and returns parsed {timestamp, action, outcome, subject, resource}. No credential reaches
	// the browser. Governed without a session → 401; no observability stack → 501; auth-off dev → open.
	import {
		createSvelteTable,
		DataTable,
		DataTableHeaderButton,
		DataTableTextFilter,
		getCoreRowModel,
		getFilteredRowModel,
		getPaginationRowModel,
		getSortedRowModel,
		renderComponent,
		renderSnippet,
		type ColumnDef,
		type PaginationState,
		type SortingState,
	} from '@rask/ui/data-table';
	import { Select } from '@rask/ui/select';
	import { RefreshCw, ScrollText, ShieldAlert } from '@lucide/svelte';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { requestJSON } from './http';

	// Return here after the OIDC round-trip (the shell's ?redirect= contract, nav-user.svelte).
	const loginHref = $derived(`/auth/login?redirect=${encodeURIComponent(page.url.pathname)}`);

	type AuditEvent = {
		timestamp: string;
		action: string;
		outcome: string;
		subject: string;
		resource: string;
	};

	let events = $state<AuditEvent[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let inflight = 0;

	// Filters (applied server-side by the BFF over the returned columns).
	let outcome = $state('');
	let action = $state('');
	let subject = $state('');
	let resource = $state('');

	const unauthorized = $derived(events === null && settled && lastStatus === 401);
	const forbidden = $derived(events === null && settled && lastStatus === 403);
	const unavailable = $derived(events === null && settled && lastStatus === 501);
	// 0 stays IN the offline set: after the first settle, a fetch-level failure (network down, BFF timeout)
	// reports status 0 and must render as offline, not hang on the loading message (audit finding).
	const offline = $derived(
		events === null && settled && ![200, 401, 403, 501].includes(lastStatus),
	);

	async function load(): Promise<void> {
		const seq = ++inflight;
		const q = new URLSearchParams();
		if (outcome) q.set('outcome', outcome);
		if (action.trim()) q.set('action', action.trim());
		if (subject.trim()) q.set('subject', subject.trim());
		if (resource.trim()) q.set('resource', resource.trim());
		const res = await requestJSON<{ events: AuditEvent[] }>('/api', `audit?${q}`);
		if (seq !== inflight) return; // latest-wins
		settled = true;
		if (res.ok) {
			events = res.data.events;
			lastStatus = 200;
		} else {
			// Clear the stale rows on failure so the auth/forbidden/offline state reflects reality — else a
			// session that expires mid-view would keep showing the old (privileged) trail. (audit 2026-07-20)
			events = null;
			lastStatus = res.status;
		}
	}

	// Load on mount and when the OUTCOME picker changes (tracked). The text filters are read untracked, so
	// typing does NOT re-fire a GreptimeDB query per keystroke — those apply on the explicit Search button.
	$effect(() => {
		void outcome;
		untrack(() => load());
	});

	function tone(o: string): string {
		if (o === 'DENY' || o === 'FAILURE') return 'deny';
		if (o === 'ALLOW' || o === 'SUCCESS') return 'allow';
		return '';
	}
	function when(ts: string): string {
		const d = new Date(ts);
		return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
	}

	// ── the DataTable (goal cond 4): sortable columns + a client-side text search over the
	// server-filtered window (the Search button's filters stay the GreptimeDB-side query). ──
	let sorting = $state<SortingState>([]);
	let globalFilter = $state('');
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

	const columns: ColumnDef<AuditEvent>[] = [
		{
			id: 'when',
			accessorKey: 'timestamp',
			header: sortableHeader('when'),
			cell: ({ row }) => renderSnippet(whenCell, row.original),
			meta: { cellClass: 'whitespace-nowrap' },
		},
		{
			id: 'action',
			accessorKey: 'action',
			header: sortableHeader('action'),
			cell: ({ row }) => renderSnippet(plainCell, row.original.action),
			meta: { cellClass: 'font-mono' },
		},
		{
			id: 'outcome',
			accessorKey: 'outcome',
			header: sortableHeader('outcome'),
			cell: ({ row }) => renderSnippet(outcomeCell, row.original),
			meta: { headerClass: 'w-28' },
		},
		{
			id: 'subject',
			accessorKey: 'subject',
			header: sortableHeader('subject'),
			cell: ({ row }) => renderSnippet(plainCell, row.original.subject),
			meta: { cellClass: 'font-mono' },
		},
		{
			id: 'resource',
			accessorKey: 'resource',
			header: sortableHeader('resource'),
			cell: ({ row }) => renderSnippet(plainCell, row.original.resource),
			meta: { cellClass: 'font-mono' },
		},
	];

	const table = createSvelteTable({
		get data() {
			return events ?? [];
		},
		columns,
		state: {
			get sorting() {
				return sorting;
			},
			get globalFilter() {
				return globalFilter;
			},
			get pagination() {
				return pagination;
			},
		},
		onSortingChange: (u) => (sorting = typeof u === 'function' ? u(sorting) : u),
		onGlobalFilterChange: (u) => (globalFilter = typeof u === 'function' ? u(globalFilter) : u),
		onPaginationChange: (u) => (pagination = typeof u === 'function' ? u(pagination) : u),
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getFilteredRowModel: getFilteredRowModel(),
		getPaginationRowModel: getPaginationRowModel(),
	});
</script>

{#snippet whenCell(e: AuditEvent)}
	<span class="mono when">{when(e.timestamp)}</span>
{/snippet}
{#snippet plainCell(value: string)}
	<span class="mono">{value || '—'}</span>
{/snippet}
{#snippet outcomeCell(e: AuditEvent)}
	<span class="mono {tone(e.outcome)}">{e.outcome || '—'}</span>
{/snippet}

<div class="page">
	<header>
		<ScrollText size={16} />
		<h1>Audit log</h1>
		<span class="sub mono">who / what / outcome · #41 compliance trail from GreptimeDB</span>
	</header>

	<div class="filters">
		<Select
			bind:value={outcome}
			ariaLabel="Outcome filter"
			placeholder="any outcome"
			options={[
				{ value: '', label: 'any outcome' },
				{ value: 'ALLOW', label: 'ALLOW' },
				{ value: 'DENY', label: 'DENY' },
				{ value: 'SUCCESS', label: 'SUCCESS' },
				{ value: 'FAILURE', label: 'FAILURE' },
			]}
		/>
		<input
			class="mono"
			bind:value={action}
			placeholder="action (e.g. can_drop)"
			aria-label="Action filter"
		/>
		<input
			class="mono"
			bind:value={subject}
			placeholder="subject contains…"
			aria-label="Subject filter"
		/>
		<input
			class="mono"
			bind:value={resource}
			placeholder="resource contains…"
			aria-label="Resource filter"
		/>
		<button class="btn" onclick={load}>Search</button>
	</div>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={15} /> <a href={loginHref} data-sveltekit-reload>Sign in</a> to view the audit
			trail.
		</div>
	{:else if forbidden}
		<div class="empty">
			<ShieldAlert size={15} /> The audit trail is estate-admin only — it spans every tenant.
		</div>
	{:else if unavailable}
		<div class="empty">The audit viewer needs the observability stack (GreptimeDB).</div>
	{:else if offline}
		<div class="empty"><RefreshCw size={15} /> Audit store unreachable (HTTP {lastStatus}).</div>
	{:else}
		<div class="toolbar">
			<DataTableTextFilter bind:value={globalFilter} placeholder="Search this window…" />
		</div>
		<DataTable
			{table}
			loading={events === null}
			emptyMessage="No audit events match — widen the filters, or the trail is empty for this window."
		/>
	{/if}
</div>

<style>
	.page {
		max-width: 980px;
		margin: 0 auto;
		padding: 56px 20px 40px;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 16px;
	}
	h1 {
		font-size: 20px;
		margin: 0;
	}
	.sub {
		color: var(--faint);
		font-size: 12px;
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 14px;
	}
	.filters input {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 8px;
		flex: 1 1 160px;
		min-width: 120px;
	}
	.btn {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 14px;
		cursor: pointer;
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		font-size: 13px;
		padding: 30px 0;
	}
	.toolbar {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.when {
		color: var(--faint);
		white-space: nowrap;
	}
	.allow {
		color: var(--ok);
	}
	.deny {
		color: var(--fail);
	}
</style>
