<script lang="ts">
	import '../app.css';
	import type { LayoutServerData } from './$types';

	let { children, data }: { children: import('svelte').Snippet; data: LayoutServerData } = $props();
</script>

{#if data.authEnabled}
	<div class="authbar">
		{#if data.user}
			<span class="who" title={data.user.email ?? undefined}>{data.user.name}</span>
			<form method="POST" action="/auth/logout">
				<button type="submit" class="btn">Sign out</button>
			</form>
		{:else}
			<a class="btn primary" href="/auth/login">Sign in</a>
		{/if}
	</div>
{/if}

{@render children()}

<style>
	.authbar {
		position: fixed;
		top: 10px;
		right: 12px;
		z-index: 50;
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: ui-sans-serif, system-ui, sans-serif;
		font-size: 12px;
	}
	.who {
		color: var(--mut);
	}
	.btn {
		padding: 4px 10px;
		border: 1px solid var(--line);
		border-radius: 7px;
		background: var(--panel-2);
		color: var(--ink);
		font: inherit;
		cursor: pointer;
		text-decoration: none;
	}
	.btn.primary {
		border-color: color-mix(in srgb, var(--accent, #ffc14d) 60%, var(--line));
	}
	.btn:hover {
		background: var(--panel);
	}
</style>
