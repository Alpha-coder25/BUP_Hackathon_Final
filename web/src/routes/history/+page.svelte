<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import { fmtLiters } from '$lib/format';

	// Filters — $state, filtered lists via $derived (FrontendImplementation §3).
	let fStation = $state('');
	let fFuel = $state('');
	let fDate = $state('');

	const fuels = $derived([...new Set(sim.allocations.map((a) => a.fuel_type))].sort());
	const stations = $derived([
		...new Set([
			...sim.allocations.map((a) => a.destination_station_id),
			...sim.decisions.map((d) => '')
		])
	].filter(Boolean).sort());
	// Station choices come from allocations; decisions join through recommendation_id,
	// so the filter applies to allocations and (via note text) shows all decisions.

	const allocations = $derived(
		sim.allocations.filter(
			(a) =>
				(!fStation || a.destination_station_id === fStation) &&
				(!fFuel || a.fuel_type === fFuel) &&
				(!fDate || new Date(a.created_tick * 15 * 60 * 1000).toISOString().startsWith(fDate))
		)
	);

	const decisions = $derived(
		sim.decisions.filter((d) => {
			if (!fDate) return true;
			return d.decided_at.startsWith(fDate);
		})
	);

	$effect(() => {
		sim.refreshHistory().catch(() => {});
	});
</script>

<h1>History</h1>

<div class="filters">
	<select bind:value={fStation}>
		<option value="">All stations</option>
		{#each stations as s (s)}
			<option value={s}>{s}</option>
		{/each}
	</select>
	<select bind:value={fFuel}>
		<option value="">All fuels</option>
		{#each fuels as f (f)}
			<option value={f}>{f}</option>
		{/each}
	</select>
	<input type="date" bind:value={fDate} />
	{#if fStation || fFuel || fDate}
		<button class="clear" onclick={() => { fStation = ''; fFuel = ''; fDate = ''; }}>Clear</button>
	{/if}
</div>

<section>
	<h2>Allocations</h2>
	{#if allocations.length === 0}
		<p class="empty">No allocations match.</p>
	{:else}
		<table>
			<thead>
				<tr><th>Depot → Station</th><th>Route</th><th>Fuel</th><th>Qty</th><th>Status</th><th>Failure</th></tr>
			</thead>
			<tbody>
				{#each allocations as a (a.id)}
					<tr>
						<td>{a.source_depot_id} → {a.destination_station_id}</td>
						<td>{a.route_id}</td>
						<td>{a.fuel_type}</td>
						<td class="num">{fmtLiters(a.quantity)}</td>
						<td class="status" style:--c={a.status === 'ARRIVED' ? 'var(--color-ok)' : a.status === 'FAILED' || a.status === 'CANCELLED' ? 'var(--sev-critical)' : 'var(--sev-medium)'}>
							{a.status}
						</td>
						<td class="fail">{a.failure_reason ?? ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</section>

<section>
	<h2>Decisions</h2>
	{#if decisions.length === 0}
		<p class="empty">No decisions match.</p>
	{:else}
		<table>
			<thead>
				<tr><th>When</th><th>Operator</th><th>Action</th><th>Rec #</th><th>Note</th></tr>
			</thead>
			<tbody>
				{#each decisions as d (d.id)}
					<tr>
						<td>{new Date(d.decided_at).toLocaleString()}</td>
						<td>{d.operator}</td>
						<td class="status" style:--c={d.action === 'APPROVED' ? 'var(--color-ok)' : d.action === 'REJECTED' ? 'var(--sev-critical)' : 'var(--sev-medium)'}>
							{d.action}
						</td>
						<td>#{d.recommendation_id}</td>
						<td class="fail">{d.note}</td>
		</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</section>

<style>
	h1 {
		font-size: var(--text-2xl);
		margin: 0 0 var(--space-7);
	}
	h2 {
		font-size: var(--text-lg);
		color: var(--text-tertiary);
		margin: var(--space-8) 0 var(--space-5);
	}
	.filters {
		display: flex;
		gap: var(--space-6);
		align-items: center;
		margin-bottom: var(--space-7);
	}
	select,
	input {
		background: var(--surface-raised);
		color: var(--text-primary);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-3) var(--space-5);
		font-size: var(--text-md);
		font-family: inherit;
		transition: border-color var(--motion-instant) ease;
	}
	select:hover,
	input:hover {
		border-color: var(--text-tertiary);
	}
	.clear {
		background: transparent;
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		color: var(--text-tertiary);
		cursor: pointer;
		padding: var(--space-3) var(--space-6);
		font-size: var(--text-md);
		font-family: inherit;
		transition: border-color var(--motion-instant) ease, background var(--motion-instant) ease;
	}
	.clear:hover:not(:disabled) {
		border-color: var(--text-tertiary);
		background: var(--surface-strong);
	}
	.clear:active:not(:disabled) {
		background: var(--surface-muted);
	}
	.clear:disabled {
		opacity: 0.5;
		cursor: default;
	}
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
	}
	th {
		color: var(--text-tertiary);
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.num {
		font-variant-numeric: tabular-nums;
	}
	.status {
		font-weight: 600;
		font-size: var(--text-md);
		color: var(--c);
	}
	.fail {
		color: var(--text-secondary);
		font-size: var(--text-md);
	}
	.empty {
		color: var(--text-secondary);
	}
</style>
