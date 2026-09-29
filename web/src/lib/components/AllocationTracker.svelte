<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';

	let { recommendationId }: { recommendationId: number } = $props();

	// Allocations mirror the simulator ledger; statuses arrive via SSE
	// allocation.status_changed → sim store refetch (FrontendImplementation §3).
	const allocations = $derived(sim.allocations.filter((a) => a.recommendation_id === recommendationId));

	const STEPS = ['PENDING', 'IN_TRANSIT', 'ARRIVED'] as const;
</script>

{#each allocations as a (a.id)}
	<div class="alloc">
		<span class="key">{a.idempotency_key}</span>
		<span class="steps">
			{#each STEPS as step, i (step)}
				<span class="step" class:done={STEPS.indexOf(a.status as 'PENDING') >= i} class:failed={a.status === 'FAILED'}>
					{step}
				</span>
				{#if i < STEPS.length - 1}<span class="arrow">→</span>{/if}
			{/each}
		</span>
		{#if a.status === 'FAILED'}
			<span class="fail">{a.failure_reason ?? 'FAILED'}</span>
		{:else if a.status === 'CANCELLED'}
			<span class="fail">CANCELLED</span>
		{/if}
	</div>
{/each}

<style>
	.alloc {
		display: flex;
		align-items: center;
		gap: var(--space-6);
		font-size: var(--text-md);
		padding: var(--space-3) 0;
		border-top: var(--space-1) dashed var(--border-muted);
	}
	.key {
		color: var(--text-tertiary);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}
	.steps {
		display: flex;
		gap: var(--space-3);
		align-items: center;
	}
	.step {
		color: var(--text-tertiary);
		letter-spacing: 0.03em;
		font-size: var(--text-sm);
	}
	.step.done {
		color: var(--color-ok);
		font-weight: 600;
	}
	.step.failed {
		color: var(--sev-critical);
		font-weight: 600;
	}
	.arrow {
		color: var(--text-secondary);
	}
	.fail {
		color: var(--sev-critical);
		font-size: var(--text-sm);
	}
</style>
