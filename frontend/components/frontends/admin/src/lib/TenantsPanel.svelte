<script lang="ts">
	// `/tenants` — the estate's tenants, enumerated from the catalog's first-class projects API
	// (grouped warehouse registry + FGA admins; estate-admin gated BY THE CATALOG — the BFF only
	// bearer-forwards). Read-only observability: creation stays implicit via the warehouse-bind flow.
	import { Building2, RefreshCw, ShieldAlert } from '@lucide/svelte';
	import { parse } from '@rask/api';
	import { page } from '$app/state';
	import { ProjectsResponseSchema, type Project } from './tenants';
	import { requestJSON } from './http';

	// Return here after the OIDC round-trip (the shell's ?redirect= contract, nav-user.svelte).
	const loginHref = $derived(`/auth/login?redirect=${encodeURIComponent(page.url.pathname)}`);

	let projects = $state<Project[] | null>(null);
	let lastStatus = $state(0);
	let settled = $state(false);
	let inflight = 0;

	const unauthorized = $derived(projects === null && settled && lastStatus === 401);
	const forbidden = $derived(projects === null && settled && lastStatus === 403);
	const drifted = $derived(projects === null && settled && lastStatus === -1);
	const offline = $derived(
		projects === null && settled && ![-1, 200, 401, 403].includes(lastStatus),
	);

	async function load(): Promise<void> {
		const seq = ++inflight;
		const res = await requestJSON<unknown>('/api', 'projects');
		if (seq !== inflight) return; // latest-wins
		settled = true;
		if (res.ok) {
			try {
				projects = parse(ProjectsResponseSchema, res.data);
				lastStatus = 200;
			} catch (err) {
				console.error(`tenants parse failure: ${String(err)}`);
				projects = null;
				lastStatus = -1;
			}
		} else {
			projects = null;
			lastStatus = res.status;
		}
	}

	$effect(() => {
		load();
	});
</script>

<div class="page">
	<header>
		<Building2 size={16} />
		<h1>Tenants</h1>
		<span class="sub mono">projects · warehouses · admins — derived from the registry + FGA</span>
	</header>

	<div class="bar">
		<button class="btn" onclick={load}><RefreshCw size={13} /> Refresh</button>
	</div>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={15} /> <a href={loginHref} data-sveltekit-reload>Sign in</a> to view tenants.
		</div>
	{:else if forbidden}
		<div class="empty">
			<ShieldAlert size={15} /> Tenant enumeration is estate-admin only.
		</div>
	{:else if drifted}
		<div class="empty">
			<ShieldAlert size={15} /> The projects payload drifted from the contract — refusing to render.
		</div>
	{:else if offline}
		<div class="empty"><RefreshCw size={15} /> Catalog unreachable (HTTP {lastStatus}).</div>
	{:else if projects === null}
		<div class="empty">Loading tenants…</div>
	{:else if projects.length === 0}
		<div class="empty">
			No projects yet — the first warehouse-create brings its project into existence.
		</div>
	{:else}
		{#each projects as p (p.project)}
			<section class="tenant">
				<div class="head">
					<span class="name mono">{p.project}</span>
					<span class="count">
						{p.warehouses.length} warehouse{p.warehouses.length === 1 ? '' : 's'}
					</span>
				</div>
				<table>
					<thead><tr><th>warehouse</th><th>bucket</th><th>status</th></tr></thead>
					<tbody>
						{#each p.warehouses as w (w.id)}
							<tr>
								<td class="mono">{w.id}</td>
								<td class="mono">{w.bucket}</td>
								<td class:warn={w.status !== 'active'}>{w.status}</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<div class="admins">
					admins:
					{#if p.admins.length === 0}
						<span class="mut">(none listed — FGA off or unavailable)</span>
					{:else}
						{#each p.admins as a (a)}<span class="chip mono">{a}</span>{/each}
					{/if}
					<a class="jump" href="/data/warehouses" data-sveltekit-reload>warehouses ↗</a>
					<a class="jump" href="/data/namespaces" data-sveltekit-reload>namespaces ↗</a>
				</div>
			</section>
		{/each}
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
	.bar {
		display: flex;
		gap: 8px;
		margin-bottom: 14px;
	}
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 4px 12px;
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
	.tenant {
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		padding: 12px 14px;
		margin-bottom: 12px;
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 8px;
	}
	.name {
		font-size: 14px;
		font-weight: 600;
		color: var(--ink);
	}
	.count {
		color: var(--faint);
		font-size: 12px;
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
		margin-bottom: 8px;
	}
	th {
		text-align: left;
		color: var(--faint);
		font-weight: 500;
		padding: 3px 14px 3px 0;
		border-bottom: 1px solid var(--line);
	}
	td {
		padding: 3px 14px 3px 0;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
	}
	td.warn {
		color: var(--warn);
	}
	.admins {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		color: var(--faint);
		font-size: 12px;
	}
	.chip {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 1px 8px;
		color: var(--ink);
	}
	.mut {
		color: var(--mut);
	}
	.jump {
		margin-left: auto;
		color: var(--mut);
		text-decoration: none;
	}
	.jump + .jump {
		margin-left: 0;
	}
	.mono {
		font-family: ui-monospace, monospace;
	}
</style>
