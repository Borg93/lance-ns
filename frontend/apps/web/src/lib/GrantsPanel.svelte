<script lang="ts">
	// The dataset panel's access-review section (#51): who holds which can_* action on the table,
	// expanded through the FGA model (roles, teams, the parent cascade). Owner-only by design — the
	// catalog gates the enumeration on can_drop, so a non-owner sees the denial state, never the ACL.
	// Collapsed by default: one owner-tier round-trip per dataset, with definitive outcomes (the ACL,
	// 401/403/501) cached and transient failures (offline, 5xx) retried on the next open.
	import { ChevronRight, ShieldCheck } from "@lucide/svelte";
	import { type AccessList, fetchTableAccess } from "./catalog";

	let { dataset }: { dataset: string } = $props();

	// Every piece of state is keyed by the dataset it belongs to (no cross-dataset bleed, audit
	// 2026-07-16: a single un-keyed `loading` let one dataset's in-flight review block another's):
	// the panel is open only for the dataset it was opened on, a review/spinner/failure is shown
	// only for the dataset it was produced for — switching datasets blanks them by derivation.
	let openedFor = $state<string | null>(null);
	let review = $state<{ for: string; access: AccessList | null; denied: string | null } | null>(
		null,
	);
	let loadingFor = $state<string | null>(null);
	let failedFor = $state<string | null>(null); // transient failure — never cached, reopen retries

	const open = $derived(openedFor === dataset);
	const shown = $derived(review?.for === dataset ? review : null);
	const loading = $derived(loadingFor === dataset);
	const failed = $derived(failedFor === dataset);

	async function toggle(): Promise<void> {
		if (open) {
			openedFor = null;
			return;
		}
		openedFor = dataset;
		if (shown !== null || loading) return;
		loadingFor = dataset;
		failedFor = null;
		const current = dataset;
		try {
			const res = await fetchTableAccess(current);
			// Latest-wins: the user clicked away while this was in flight — drop the stale result.
			if (dataset !== current) return;
			if (res.ok) {
				review = { for: current, access: res.data, denied: null };
			} else if (res.status === 401 || res.status === 403 || res.status === 501) {
				const denied =
					res.status === 401
						? "Sign in to review access."
						: res.status === 403
							? "Owner access required to review who can reach this table."
							: "This stack runs auth-off — there are no grants to review.";
				review = { for: current, access: null, denied };
			} else {
				failedFor = current; // offline / 5xx: shown but not cached, so the next open retries
			}
		} finally {
			if (loadingFor === current) loadingFor = null;
		}
	}

	// Hide the empty rows: a relation nobody holds is noise in a review of who has access.
	const held = $derived(shown?.access ? shown.access.grants.filter((g) => g.users.length > 0) : []);
</script>

<div class="grants">
	<button class="head" onclick={toggle} aria-expanded={open}>
		<span class="chev" class:open><ChevronRight size={12} /></span>
		<ShieldCheck size={12} />
		<span>Access review</span>
	</button>
	{#if open}
		{#if loading}
			<p class="mut">Reviewing access…</p>
		{:else if failed}
			<p class="mut">Access review unavailable right now — close and reopen to retry.</p>
		{:else if shown?.denied}
			<p class="mut">{shown.denied}</p>
		{:else if shown?.access}
			{#if held.length === 0}
				<p class="mut">No user holds any action on this table (grants may target roles only).</p>
			{:else}
				<table class="acl">
					<thead><tr><th>action</th><th>who</th></tr></thead>
					<tbody>
						{#each held as grant (grant.relation)}
							<tr>
								<td class="mono rel">{grant.relation}</td>
								<td>
									{#each grant.users as user (user)}
										<span class="who mono" class:wild={user === "*"}
											>{user === "*" ? "everyone (*)" : user}</span
										>
									{/each}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.grants {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 2px 0 10px;
	}
	.head {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		background: none;
		border: none;
		padding: 0;
		color: var(--mut);
		font: inherit;
		font-size: 12px;
		cursor: pointer;
	}
	.head:hover {
		color: var(--ink);
	}
	.chev {
		display: inline-flex;
		transition: transform 0.12s ease;
	}
	.chev.open {
		transform: rotate(90deg);
	}
	.mut {
		color: var(--faint);
		font-size: 12px;
		margin: 0;
	}
	.acl {
		border-collapse: collapse;
		font-size: 12px;
	}
	.acl th {
		text-align: left;
		color: var(--faint);
		font-weight: 500;
		padding: 2px 14px 2px 0;
	}
	.acl td {
		padding: 2px 14px 2px 0;
		vertical-align: top;
	}
	.rel {
		color: var(--mut);
		white-space: nowrap;
	}
	.who {
		display: inline-block;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		padding: 0 6px;
		margin: 0 4px 3px 0;
	}
	.who.wild {
		border-color: color-mix(in srgb, var(--amber) 55%, var(--line));
	}
</style>
