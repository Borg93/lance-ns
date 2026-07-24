<script lang="ts">
	// `/warehouses` — the #3-A control plane (#52 UI): provisioned warehouses (bucket-per-warehouse
	// physical tenancy), activate/deactivate lifecycle, namespace binding, and provisioning. Reads
	// are session-forwarded; writes are project-admin gated by the catalog (can_create_warehouse /
	// can_administer) — a non-admin sees the denial banner, never a silent no-op.
	import { Select } from '@rask/ui/select';
	import { RefreshCw, ShieldAlert, Warehouse as WarehouseIcon } from '@lucide/svelte';
	import { page } from '$app/state';
	import {
		bindWarehouseNamespace,
		createWarehouse,
		fetchWarehouses,
		setWarehouseActive,
		type Warehouse,
	} from './catalog';

	const POLL_MS = 5000;

	// Return here after the OIDC round-trip (the shell's ?redirect= contract, nav-user.svelte).
	const loginHref = $derived(`/auth/login?redirect=${encodeURIComponent(page.url.pathname)}`);

	let warehouses = $state<Warehouse[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let busy = $state(false);
	let banner = $state<{ tone: 'ok' | 'fail'; text: string } | null>(null);
	let draft = $state({ id: '', project: '', bucket: '' });
	let bindDraft = $state<{ warehouse: string; namespace: string }>({
		warehouse: '',
		namespace: '',
	});

	const unauthorized = $derived(warehouses === null && lastStatus === 401);
	const offline = $derived(warehouses === null && settled && lastStatus !== 401);

	// A pre-lifecycle warehouse (provisioned before the activate/deactivate feature) has no `status`
	// field — treat that as active, so it renders active with the correct toggle direction.
	function statusOf(w: Warehouse): string {
		return w.status ?? 'active';
	}

	async function load(): Promise<void> {
		const res = await fetchWarehouses();
		settled = true;
		if (res.ok) {
			warehouses = res.data;
			lastStatus = 200;
		} else {
			lastStatus = res.status;
		}
	}

	$effect(() => {
		load();
		const timer = setInterval(load, POLL_MS);
		return () => clearInterval(timer);
	});

	function fail(status: number, detail: string): void {
		if (status === 401)
			banner = { tone: 'fail', text: 'Sign in — warehouse admin is a per-user action.' };
		else if (status === 403 || status === 404)
			// The lifecycle ops hide existence from non-admins (a denied deactivate is a 404, not a 403),
			// so both map to the same admin-required message.
			banner = { tone: 'fail', text: 'Denied: warehouse admin needs the project-admin rung.' };
		else banner = { tone: 'fail', text: detail };
	}

	async function provision(): Promise<void> {
		if (busy || !draft.id.trim() || !draft.project.trim()) return;
		busy = true;
		banner = null;
		try {
			const res = await createWarehouse({
				id: draft.id.trim(),
				project: draft.project.trim(),
				bucket: draft.bucket.trim() || null,
			});
			if (res.ok) {
				banner = {
					tone: 'ok',
					text: `warehouse ${res.data.id} provisioned (${res.data.root_uri})`,
				};
				draft = { id: '', project: '', bucket: '' };
				await load();
			} else {
				fail(res.status, res.detail);
			}
		} finally {
			busy = false;
		}
	}

	async function toggleActive(w: Warehouse): Promise<void> {
		if (busy) return;
		busy = true;
		banner = null;
		try {
			const res = await setWarehouseActive(w.id, statusOf(w) !== 'active');
			if (res.ok) await load();
			else fail(res.status, res.detail);
		} finally {
			busy = false;
		}
	}

	async function bind(): Promise<void> {
		if (busy || !bindDraft.warehouse || !bindDraft.namespace.trim()) return;
		busy = true;
		banner = null;
		try {
			const res = await bindWarehouseNamespace(bindDraft.warehouse, bindDraft.namespace.trim());
			if (res.ok) {
				banner = {
					tone: 'ok',
					text: `namespace ${bindDraft.namespace} bound to ${bindDraft.warehouse}`,
				};
				bindDraft = { warehouse: '', namespace: '' };
			} else {
				fail(res.status, res.detail);
			}
		} finally {
			busy = false;
		}
	}
</script>

<div class="page">
	<header>
		<WarehouseIcon size={16} />
		<h1>Warehouses</h1>
		<span class="sub mono">bucket-per-warehouse physical tenancy · project-admin gated</span>
	</header>

	{#if banner}
		<div class="banner" class:ok={banner.tone === 'ok'} class:fail={banner.tone === 'fail'}>
			{banner.text}
		</div>
	{/if}

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={16} />
			<p>
				This stack is governed — <a href={loginHref} data-sveltekit-reload>sign in</a> to view warehouses.
			</p>
		</div>
	{:else if offline}
		<div class="empty">
			<RefreshCw size={16} />
			<p>Catalog unreachable (HTTP {lastStatus}) — retrying.</p>
		</div>
	{:else if warehouses === null}
		<div class="empty"><p>Loading…</p></div>
	{:else}
		{#if warehouses.length === 0}
			<div class="empty"><p>No warehouses provisioned — the form below creates the first.</p></div>
		{:else}
			<table>
				<thead>
					<tr><th>id</th><th>project</th><th>bucket</th><th>status</th><th></th></tr>
				</thead>
				<tbody>
					{#each warehouses as w (w.id)}
						<tr>
							<td class="mono">{w.id}</td>
							<td class="mono">{w.project}</td>
							<td class="mono">{w.bucket}</td>
							<td
								><span class="chip mono" class:off={statusOf(w) !== 'active'}>{statusOf(w)}</span
								></td
							>
							<td class="actions">
								<button class="btn ghost" disabled={busy} onclick={() => toggleActive(w)}>
									{statusOf(w) === 'active' ? 'deactivate' : 'activate'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<section>
			<h2>Provision</h2>
			<form
				class="row"
				onsubmit={(e) => {
					e.preventDefault();
					provision();
				}}
			>
				<input
					class="mono"
					bind:value={draft.id}
					placeholder="warehouse id"
					aria-label="Warehouse id"
				/>
				<input class="mono" bind:value={draft.project} placeholder="project" aria-label="Project" />
				<input
					class="mono"
					bind:value={draft.bucket}
					placeholder="bucket (defaults to id)"
					aria-label="Bucket"
				/>
				<button
					class="btn"
					type="submit"
					disabled={busy || !draft.id.trim() || !draft.project.trim()}
				>
					Provision
				</button>
			</form>
		</section>

		<section>
			<h2>Bind namespace</h2>
			<form
				class="row"
				onsubmit={(e) => {
					e.preventDefault();
					bind();
				}}
			>
				<Select
					bind:value={bindDraft.warehouse}
					ariaLabel="Warehouse"
					placeholder="warehouse…"
					options={warehouses.map((w) => ({ value: w.id, label: w.id }))}
				/>
				<input
					class="mono"
					bind:value={bindDraft.namespace}
					placeholder="top-level namespace"
					aria-label="Namespace"
				/>
				<button
					class="btn"
					type="submit"
					disabled={busy || !bindDraft.warehouse || !bindDraft.namespace.trim()}
				>
					Bind
				</button>
			</form>
			<p class="mut">
				Binding routes a top-level namespace's tables to the warehouse's bucket (immutable once
				set).
			</p>
		</section>
	{/if}
</div>

<style>
	.page {
		max-width: 860px;
		margin: 0 auto;
		padding: 56px 20px 40px;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 18px;
	}
	h1 {
		font-size: 20px;
		margin: 0;
	}
	h2 {
		font-size: 13px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--faint);
		margin: 18px 0 8px;
	}
	.sub {
		color: var(--faint);
		font-size: 12px;
	}
	.banner {
		padding: 8px 12px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--line);
		margin-bottom: 12px;
		font-size: 13px;
	}
	.banner.ok {
		border-color: color-mix(in srgb, var(--ok) 45%, var(--line));
		color: var(--ok);
	}
	.banner.fail {
		border-color: color-mix(in srgb, var(--fail) 45%, var(--line));
		color: var(--fail);
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
	}
	th {
		text-align: left;
		color: var(--faint);
		font-weight: 500;
		padding: 3px 14px 3px 0;
		border-bottom: 1px solid var(--line);
	}
	td {
		padding: 5px 14px 5px 0;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
	}
	.chip {
		background: var(--panel-2);
		border: 1px solid color-mix(in srgb, var(--ok) 45%, var(--line));
		border-radius: var(--radius-sm);
		padding: 0 7px;
	}
	.chip.off {
		border-color: color-mix(in srgb, var(--amber) 55%, var(--line));
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	input {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		padding: 5px 9px;
		font-size: 12px;
	}
	.btn {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 12px;
		cursor: pointer;
	}
	.btn.ghost {
		background: none;
		color: var(--mut);
	}
	.mut {
		color: var(--faint);
		font-size: 12px;
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		padding: 32px 0;
	}
	.actions {
		text-align: right;
	}
</style>
