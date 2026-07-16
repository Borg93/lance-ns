<script lang="ts">
	import { page } from "$app/state";
	import TableDetail from "$lib/TableDetail.svelte";

	// The [table] param is required by the route, but $app/state types params loosely.
	const table = $derived(page.params.table ?? "");
</script>

<svelte:head><title>{table} · lance-ns</title></svelte:head>
<TableDetail {table} />
