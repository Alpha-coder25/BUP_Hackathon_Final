<script lang="ts">
	import { fmtLiters } from '$lib/format';
	import type { SimMetrics } from '$lib/api/types';

	let { metrics }: { metrics: SimMetrics | null } = $props();

	// Ground-truth KPIs from /v1/metrics via the collector. Service level drives
	// the tone: healthy ≥ 95%, strained ≥ 80%, crisis below that.
	const levelTone = $derived.by(() => {
		if (!metrics) return 'var(--text-tertiary)';
		const s = metrics.service_level;
		return s >= 0.95 ? 'var(--color-ok)' : s >= 0.8 ? 'var(--sev-medium)' : 'var(--sev-critical)';
	});
	const levelPct = $derived(metrics ? `${(metrics.service_level * 100).toFixed(1)}%` : '—');
</script>

<section class="metrics" aria-label="Simulation service metrics">
	{#if metrics}
		<div class="cell">
			<span class="label">Service level</span>
			<span class="value" style:color={levelTone}>{levelPct}</span>
		</div>
		<div class="cell">
			<span class="label">Served</span>
			<span class="value">{fmtLiters(metrics.served_demand_liters)}</span>
		</div>
		<div class="cell">
			<span class="label">Unmet</span>
			<span
				class="value"
				style:color={metrics.unmet_demand_liters > 0 ? 'var(--sev-high)' : 'var(--text-inverse)'}
			>
				{fmtLiters(metrics.unmet_demand_liters)}
			</span>
		</div>
		<div class="cell">
			<span class="label">Allocated</span>
			<span class="value">{fmtLiters(metrics.allocation_liters)}</span>
		</div>
		<div class="cell">
			<span class="label">Failures</span>
			<span
				class="value"
				style:color={metrics.allocation_failures > 0 ? 'var(--sev-critical)' : 'var(--text-inverse)'}
			>
				{metrics.allocation_failures}
			</span>
		</div>
	{:else}
		<p class="empty">Service metrics appear once the collector publishes its first snapshot.</p>
	{/if}
</section>

<style>
	.metrics {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: var(--space-5);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		background: var(--surface-muted);
		box-shadow: var(--shadow-1);
		padding: var(--space-7) var(--space-8);
		margin: 0 0 var(--space-8);
	}
	.cell {
		display: grid;
		gap: var(--space-2);
	}
	.label {
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-tertiary);
	}
	.value {
		font-size: var(--text-2xl);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--text-inverse);
	}
	.empty {
		margin: 0;
		grid-column: 1 / -1;
		font-size: var(--text-lg);
		color: var(--text-secondary);
	}
</style>
