<script lang="ts">
	let { status }: { status: string } = $props();

	const kind = $derived(
		status === 'OPEN'
			? 'ok'
			: status === 'CONSTRAINED'
				? 'warn'
				: 'crit' // OUTAGE and anything unknown
	);
</script>

<span class="chip" style:--c={kind === 'ok' ? 'var(--color-ok)' : kind === 'warn' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
	{status}
</span>

<style>
	.chip {
		display: inline-block;
		font-size: var(--text-sm);
		font-weight: 600;
		letter-spacing: 0.04em;
		padding: var(--space-1) var(--space-5);
		border-radius: var(--radius-sm);
		border: var(--space-1) solid var(--c);
		color: var(--c);
	}
</style>
