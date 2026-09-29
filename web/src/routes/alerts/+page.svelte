<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import AlertCard from '$lib/components/AlertCard.svelte';

	const active = $derived(sim.alerts.filter((a) => a.status !== 'RESOLVED'));
</script>

<h1>Alerts</h1>

{#if active.length === 0}
	<p class="empty">No active alerts.</p>
{:else}
	<div class="feed">
		{#each active as alert (alert.id)}
			<AlertCard {alert} />
		{/each}
	</div>
{/if}

<style>
	h1 {
		font-size: var(--text-2xl);
		margin: 0 0 var(--space-8);
	}
	.feed {
		display: grid;
		gap: var(--space-8);
		max-width: 720px;
	}
	.empty {
		color: var(--text-secondary);
	}
</style>
