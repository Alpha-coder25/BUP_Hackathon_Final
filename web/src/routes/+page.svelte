<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import { fmtLiters } from '$lib/format';
	import InventoryCard from '$lib/components/InventoryCard.svelte';
	import StatusChip from '$lib/components/StatusChip.svelte';
	import DemandTable from '$lib/components/DemandTable.svelte';
	import StationDrillIn from '$lib/components/StationDrillIn.svelte';

	let selectedStationId = $state<string | null>(null);

	const stations = $derived(sim.state?.stations ?? []);
	const depots = $derived(sim.state?.depots ?? []);
	const arrivals = $derived(sim.state?.arrivals ?? []);
	const selected = $derived(stations.find((s) => s.id === selectedStationId) ?? null);
</script>

<h1>Overview</h1>

{#if !sim.state}
	<p class="empty">Waiting for backend state… (is the API on :8080 up?)</p>
{:else}
	<section>
		<h2>Depots</h2>
		<div class="grid">
			{#each depots as depot (depot.id)}
				<div class="cell">
					<div class="chiprow">
						<StatusChip status={depot.status} />
					</div>
					<InventoryCard entity={depot} fuels={['DIESEL', 'PETROL', 'OCTANE']} />
				</div>
			{/each}
		</div>
	</section>

	<section>
		<h2>Stations</h2>
		<div class="grid">
			{#each stations as station (station.id)}
				<button
					class="cell station"
 class:active={station.id === selectedStationId}
					onclick={() => (selectedStationId = station.id === selectedStationId ? null : station.id)}
				>
					<div class="chiprow">
						<StatusChip status={station.status} />
					</div>
					<InventoryCard entity={station} fuels={['DIESEL', 'PETROL', 'OCTANE']} />
				</button>
			{/each}
		</div>
	</section>

	{#if selected}
		<StationDrillIn station={selected} forecast={null} />
	{/if}

	<section>
		<h2>Regional demand (latest tick)</h2>
		<!-- demand rows land in /api/state once the collector publishes them -->
		<DemandTable rows={[]} />
	</section>

	<section>
		<h2>Incoming supply</h2>
		<ul class="arrivals">
			{#each arrivals.filter((a) => a.status !== 'ARRIVED') as a (a.id)}
				<li>
					<strong>{fmtLiters(a.quantity)}</strong> {a.fuel_type} → {a.depot_id}
					· planned T{a.planned_tick}
					{#if a.status === 'DELAYED'}<span class="delayed">DELAYED</span>{/if}
				</li>
			{/each}
		</ul>
	</section>
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 1rem;
	}
	h2 {
		font-size: 0.95rem;
		color: var(--muted);
		margin: 1.25rem 0 0.5rem;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: 0.75rem;
	}
	.cell {
		position: relative;
	}
	.chiprow {
		margin-bottom: -0.5rem;
		text-align: right;
	}
	button.station {
		all: unset;
		cursor: pointer;
		display: block;
		border-radius: 8px;
	}
	button.station:hover,
	button.station.active {
		outline: 2px solid var(--sev-medium);
	}
	.arrivals {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 0.85rem;
	}
	.arrivals li {
		padding: 0.3rem 0;
		border-bottom: 1px solid var(--line);
	}
	.delayed {
		color: var(--sev-medium);
		font-weight: 600;
		font-size: 0.7rem;
		margin-left: 0.4rem;
	}
	.empty {
		color: var(--muted);
	}
</style>
