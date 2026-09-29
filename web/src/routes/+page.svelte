<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import { fmtLiters } from '$lib/format';
	import InventoryCard from '$lib/components/InventoryCard.svelte';
	import StatusChip from '$lib/components/StatusChip.svelte';
	import DemandTable from '$lib/components/DemandTable.svelte';
	import StationDrillIn from '$lib/components/StationDrillIn.svelte';
	import MetricsStrip from '$lib/components/MetricsStrip.svelte';
	import ActiveEvents from '$lib/components/ActiveEvents.svelte';

	let selectedStationId = $state<string | null>(null);

	const stations = $derived(sim.state?.stations ?? []);
	const depots = $derived(sim.state?.depots ?? []);
	const arrivals = $derived(sim.state?.arrivals ?? []);
	const selected = $derived(stations.find((s) => s.id === selectedStationId) ?? null);

	// Latest-tick forecasts (worst severity first) for the station drill-in.
	const SEV_ORDER: Record<string, number> = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };
	const stationForecast = (stationId: string) =>
		sim.forecasts
			.filter((f) => f.station_id === stationId)
			.sort((a, b) => (SEV_ORDER[b.severity] ?? -1) - (SEV_ORDER[a.severity] ?? -1))[0] ?? null;
</script>

<h1>Overview</h1>

{#if !sim.state}
	<p class="empty">Waiting for backend state… (is the API on :8080 up?)</p>
{:else}
	<MetricsStrip metrics={sim.state.metrics} />

	<ActiveEvents events={sim.state.events} />

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
		<StationDrillIn station={selected} forecast={stationForecast(selected.id)} />
	{/if}

	<section>
		<h2>Regional demand (latest tick)</h2>
		<DemandTable rows={sim.demandRows} />
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
		font-size: var(--text-2xl);
		margin: 0 0 var(--space-8);
	}
	h2 {
		font-size: var(--text-lg);
		color: var(--text-tertiary);
		margin: var(--space-8) 0 var(--space-5);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: var(--space-8);
	}
	.cell {
		position: relative;
	}
	.chiprow {
		margin-bottom: calc(-1 * var(--space-5));
		text-align: right;
	}
	button.station {
		all: unset;
		cursor: pointer;
		display: block;
		border-radius: var(--radius-sm);
		transition: outline-color var(--motion-fast) ease;
	}
	button.station:hover {
		outline: var(--space-2) solid var(--text-tertiary);
	}
	button.station.active {
		outline: var(--space-2) solid var(--sev-medium);
	}
	.arrivals {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: var(--text-lg);
	}
	.arrivals li {
		padding: var(--space-3) 0;
		border-bottom: var(--space-1) solid var(--border-muted);
	}
	.delayed {
		color: var(--sev-medium);
		font-weight: 600;
		font-size: var(--text-sm);
		margin-left: var(--space-4);
	}
	.empty {
		color: var(--text-secondary);
	}
</style>
