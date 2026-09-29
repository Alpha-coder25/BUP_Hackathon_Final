<script lang="ts">
	import { fmtLiters } from '$lib/format';
	import type { DemandRow } from '$lib/api/types';

	let { rows }: { rows: DemandRow[] } = $props();
</script>

<table>
	<thead>
		<tr>
			<th>Station</th><th>Fuel</th><th>Demand</th><th>Served</th><th>Unmet</th>
		</tr>
	</thead>
	<tbody>
		{#each rows as row (row.station_id + row.fuel_type)}
			<tr>
				<td>{row.station_id}</td>
				<td>{row.fuel_type}</td>
				<td>{fmtLiters(row.demand_liters)}</td>
				<td>{fmtLiters(row.served_liters)}</td>
				<td class:crit={row.unmet_liters > 0}>{fmtLiters(row.unmet_liters)}</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-md);
	}
	th,
	td {
		text-align: left;
		padding: var(--space-3) var(--space-5);
		border-bottom: var(--space-1) solid var(--border-muted);
		font-variant-numeric: tabular-nums;
	}
	th {
		color: var(--text-tertiary);
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.crit {
		color: var(--sev-high);
	}
</style>
