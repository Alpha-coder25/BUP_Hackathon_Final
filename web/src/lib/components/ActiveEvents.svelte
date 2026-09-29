<script lang="ts">
	import type { SimEvent } from '$lib/api/types';

	let { events }: { events: SimEvent[] } = $props();

	// Only ACTIVE crisis events belong on the operator's radar; SCHEDULED and
	// RESOLVED ones stay in history.
	const active = $derived(events.filter((e) => e.status === 'ACTIVE'));

	const TONE: Record<SimEvent['type'], string> = {
		station_outage: 'var(--sev-critical)',
		route_disruption: 'var(--sev-critical)',
		supply_shortfall: 'var(--sev-critical)',
		demand_spike: 'var(--sev-high)',
		depot_constraint: 'var(--sev-medium)',
		shipment_delay: 'var(--sev-medium)'
	};

	const LABEL: Record<SimEvent['type'], string> = {
		demand_spike: 'Demand spike',
		route_disruption: 'Route disruption',
		station_outage: 'Station outage',
		depot_constraint: 'Depot constraint',
		shipment_delay: 'Shipment delay',
		supply_shortfall: 'Supply shortfall'
	};

	// Event parameters carry filter lists (station/route/depot/region ids);
	// an empty list means the event applies to every entity of that type.
	const scope = (e: SimEvent) => {
		const p = e.parameters ?? {};
		const ids = (p.station_ids ?? p.route_ids ?? p.depot_ids ?? p.region_ids ?? []) as string[];
		return ids.length > 0 ? ids.join(', ') : 'all entities';
	};
</script>

{#if active.length > 0}
	<div class="banner" role="status">
		<span class="title">{active.length} active crisis event{active.length === 1 ? '' : 's'}</span>
		{#each active as e (e.id)}
			<span class="event" style:--c={TONE[e.type]}>
				<b>{LABEL[e.type] ?? e.type}</b>
				T{e.start_tick}–T{e.end_tick} · {scope(e)}
			</span>
		{/each}
	</div>
{/if}

<style>
	.banner {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-5);
		border: var(--space-1) solid var(--border-muted);
		border-left: 3px solid var(--sev-critical);
		border-radius: var(--radius-sm);
		background: var(--surface-muted);
		box-shadow: var(--shadow-1);
		padding: var(--space-5) var(--space-8);
		margin: 0 0 var(--space-8);
		font-size: var(--text-md);
	}
	.title {
		font-weight: 600;
		color: var(--sev-critical);
	}
	.event {
		display: inline-flex;
		align-items: center;
		gap: var(--space-3);
		color: var(--text-secondary);
		border: var(--space-1) solid var(--c);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-4);
		font-size: var(--text-sm);
	}
	.event b {
		color: var(--c);
		font-weight: 600;
		letter-spacing: 0.03em;
	}
</style>
