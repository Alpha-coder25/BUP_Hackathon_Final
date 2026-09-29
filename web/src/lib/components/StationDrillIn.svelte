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
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-8);
		background: var(--surface-raised);
		box-shadow: var(--shadow-1);
	}
	h2 {
		margin: 0 0 var(--space-6);
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-inverse);
	}
	.grid {
		display: grid;
		gap: var(--space-5);
	}
	.label {
		display: block;
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-tertiary);
	}
	.value {
		font-variant-numeric: tabular-nums;
		font-size: var(--text-lg);
	}
	.empty {
		color: var(--text-secondary);
		font-size: var(--text-lg);
	}
</style>
