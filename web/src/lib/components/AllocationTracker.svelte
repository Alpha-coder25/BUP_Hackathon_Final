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
		gap: 0.6rem;
		font-size: 0.78rem;
		padding: 0.3rem 0;
		border-top: 1px dashed var(--line);
	}
	.key {
		color: var(--muted);
		font-family: ui-monospace, monospace;
		font-size: 0.7rem;
	}
	.steps {
		display: flex;
		gap: 0.35rem;
		align-items: center;
	}
	.step {
		color: var(--muted);
		letter-spacing: 0.03em;
		font-size: 0.7rem;
	}
	.step.done {
		color: var(--ok);
		font-weight: 600;
	}
	.step.failed {
		color: var(--sev-critical);
		font-weight: 600;
	}
	.arrow {
		color: var(--line);
	}
	.fail {
		color: var(--sev-critical);
		font-size: 0.72rem;
	}
</style>
