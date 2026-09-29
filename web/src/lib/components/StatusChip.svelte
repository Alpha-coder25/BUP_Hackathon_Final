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

<span class="chip" style:--c={kind === 'ok' ? 'var(--ok)' : kind === 'warn' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
	{status}
</span>

<style>
	.chip {
		display: inline-block;
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
		border: 1px solid var(--c);
		color: var(--c);
	}
</style>
