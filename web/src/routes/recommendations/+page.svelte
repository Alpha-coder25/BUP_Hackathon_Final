<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import RecommendationCard from '$lib/components/RecommendationCard.svelte';

	const proposed = $derived(sim.recommendations.filter((r) => r.status === 'PROPOSED'));
	const decided = $derived(sim.recommendations.filter((r) => r.status !== 'PROPOSED'));
</script>

<h1>Recommendations</h1>

{#if proposed.length === 0 && decided.length === 0}
	<p class="empty">No recommendations yet — the planner will post cards here.</p>
{:else}
	<section>
		<div class="stack">
			{#each proposed as rec (rec.id)}
				<RecommendationCard {rec} />
			{/each}
			{#each decided as rec (rec.id)}
				<RecommendationCard {rec} />
			{/each}
		</div>
	</section>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	.stack {
		display: grid;
		gap: 1rem;
		max-width: 720px;
	}
	.empty {
		color: var(--muted);
	}
</style>
