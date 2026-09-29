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
				<span class="fill" style:background={pct < 20 ? 'var(--sev-high)' : pct < 40 ? 'var(--sev-medium)' : 'var(--ok)'}></span>
			</div>
			<span class="num">{fmtLiters(inv)}</span>
		</div>
	{/each}
</div>

<style>
	.card {
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 0.75rem 1rem;
		background: var(--panel);
	}
	h3 {
		margin: 0 0 0.5rem;
		font-size: 0.95rem;
	}
	.row {
		display: grid;
		grid-template-columns: 4.5rem 1fr 5.5rem;
		gap: 0.5rem;
		align-items: center;
		margin: 0.25rem 0;
		font-size: 0.8rem;
	}
	.fuel {
		color: var(--muted);
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--line);
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
