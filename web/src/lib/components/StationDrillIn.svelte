<script lang="ts">
	import { fmtHours, severityVar } from '$lib/format';
	import type { Forecast, Station } from '$lib/api/types';

	let { station, forecast }: { station: Station; forecast: Forecast | null } = $props();

	const band = $derived(
		forecast
			? { p10: forecast.lower_bound, p50: forecast.predicted_liters, p90: forecast.upper_bound }
			: null
	);
</script>

<aside>
	<h2>{station.name} — outlook</h2>
	{#if band && forecast}
		<div class="grid">
			<div>
				<span class="label">Forecast P10 / P50 / P90</span>
				<span class="value">{band.p10} / {band.p50} / {band.p90} L</span>
			</div>
			<div>
				<span class="label">Hours to stockout</span>
				<span class="value">{fmtHours(forecast.hours_to_stockout)}</span>
			</div>
			<div>
				<span class="label">Stockout risk</span>
				<span class="value" style:color={severityVar(forecast.severity)}>
					{Math.round(forecast.stockout_probability * 100)}%
				</span>
			</div>
		</div>
	{:else}
		<p class="empty">No forecast yet for this station — intelligence pipeline warming up.</p>
	{/if}
</aside>

<style>
	aside {
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 1rem;
		background: var(--panel);
	}
	h2 {
		margin: 0 0 0.75rem;
		font-size: 1rem;
	}
	.grid {
		display: grid;
		gap: 0.5rem;
	}
	.label {
		display: block;
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted);
	}
	.value {
		font-variant-numeric: tabular-nums;
	}
	.empty {
		color: var(--muted);
		font-size: 0.85rem;
	}
</style>
