<script lang="ts">
	/** A small labelled chip — match reasons, tags, statuses. Self-contained (no app imports). */
	let { label, tone = "neutral" }: { label: string; tone?: "neutral" | "accent" } = $props();
</script>

<span class="chip" class:accent={tone === "accent"}>{label}</span>

<style>
	.chip {
		display: inline-block;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		font-size: 0.7rem;
		line-height: 1.2;
		background: color-mix(in oklab, currentColor 12%, transparent);
		border: 1px solid color-mix(in oklab, currentColor 25%, transparent);
		opacity: 0.85;
		white-space: nowrap;
	}
	.chip.accent {
		opacity: 1;
		font-weight: 600;
	}
</style>
