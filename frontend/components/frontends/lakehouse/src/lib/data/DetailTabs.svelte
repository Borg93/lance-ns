<script lang="ts">
	// The detail-page tab bar (goal cond 3): a thin, accessible tablist — Overview stays the
	// default; Access hosts the FGA view. State lives in the page (bindable), so a route can reset
	// it on id change.
	let { tabs, active = $bindable() }: { tabs: string[]; active: string } = $props();
</script>

<div class="tabs" role="tablist">
	{#each tabs as t (t)}
		<button
			type="button"
			role="tab"
			aria-selected={active === t}
			class:active={active === t}
			onclick={() => (active = t)}
		>
			{t}
		</button>
	{/each}
</div>

<style>
	.tabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--line);
		margin-bottom: 18px;
	}
	button {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--mut);
		font-size: 13px;
		padding: 6px 12px;
		cursor: pointer;
		text-transform: capitalize;
	}
	button:hover {
		color: var(--ink);
	}
	button.active {
		color: var(--ink);
		border-bottom-color: var(--accent, #ffc14d);
	}
</style>
