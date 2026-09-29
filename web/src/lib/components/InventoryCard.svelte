<script lang="ts">
	import { fmtLiters } from '$lib/format';
	import type { Depot, FuelType, Station } from '$lib/api/types';

	let {
		entity,
		fuels
	}: { entity: Depot | Station; fuels: FuelType[] } = $props();

	const FUELS: FuelType[] = ['DIESEL', 'PETROL', 'OCTANE'];
	const list = $derived(fuels ?? FUELS);
</script>

<div class="card">
	<h3>{entity.name}</h3>
	{#each list as fuel (fuel)}
		{@const inv = entity.inventory[fuel] ?? 0}
		{@const cap = entity.capacity[fuel] ?? 0}
		{@const pct = cap > 0 ? Math.round((inv / cap) * 100) : 0}
		<div class="row">
			<span class="fuel">{fuel}</span>
			<div class="bar" style:--pct="{pct}%">
				<span class="fill" style:background={pct < 20 ? 'var(--sev-high)' : pct < 40 ? 'var(--sev-medium)' : 'var(--color-ok)'}></span>
			</div>
			<span class="num">{fmtLiters(inv)}</span>
		</div>
	{/each}
</div>

<style>
	.card {
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-7) var(--space-8);
		background: var(--surface-raised);
		box-shadow: var(--shadow-1);
	}
	h3 {
		margin: 0 0 var(--space-5);
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-inverse);
	}
	.row {
		display: grid;
		grid-template-columns: 4.5rem 1fr 5.5rem;
		gap: var(--space-5);
		align-items: center;
		margin: var(--space-2) 0;
		font-size: var(--text-md);
	}
	.fuel {
		color: var(--text-secondary);
	}
	.bar {
		height: var(--space-4);
		border-radius: var(--radius-xs);
		background: var(--surface-strong);
		overflow: hidden;
	}
	.fill {
		display: block;
		height: 100%;
		width: var(--pct);
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
</style>
