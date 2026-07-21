<script lang="ts">
	let { status, message }: { status: number; message?: string } = $props();
</script>

<div
	class="bg-background text-foreground flex min-h-svh flex-col items-center justify-center gap-2"
>
	<h1 class="text-4xl font-bold">{status}</h1>
	<p class="text-muted-foreground">{message ?? 'Something went wrong.'}</p>
	<a href="/" data-sveltekit-reload class="text-primary underline">Back home</a>
</div>
