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
						<td class="status" style:--c={a.status === 'ARRIVED' ? 'var(--ok)' : a.status === 'FAILED' || a.status === 'CANCELLED' ? 'var(--sev-critical)' : 'var(--sev-medium)'}>
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
						<td class="status" style:--c={d.action === 'APPROVED' ? 'var(--ok)' : d.action === 'REJECTED' ? 'var(--sev-critical)' : 'var(--sev-medium)'}>
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
		font-size: 1.25rem;
		margin: 0 0 0.75rem;
	}
	h2 {
		font-size: 0.95rem;
		color: var(--muted);
		margin: 1.25rem 0 0.5rem;
	}
	.filters {
		display: flex;
		gap: 0.6rem;
		align-items: center;
		margin-bottom: 0.75rem;
	}
	select,
	input {
		background: var(--panel);
		color: var(--text);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 0.3rem 0.5rem;
		font-size: 0.82rem;
	}
	.clear {
		background: none;
		border: 1px solid var(--line);
		border-radius: 6px;
		color: var(--muted);
		cursor: pointer;
		padding: 0.3rem 0.6rem;
		font-size: 0.78rem;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.82rem;
	}
	th,
	td {
		text-align: left;
		padding: 0.35rem 0.55rem;
		border-bottom: 1px solid var(--line);
	}
	th {
		color: var(--muted);
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.num {
		font-variant-numeric: tabular-nums;
	}
	.status {
		font-weight: 600;
		font-size: 0.75rem;
		color: var(--c);
	}
	.fail {
		color: var(--muted);
		font-size: 0.78rem;
	}
	.empty {
		color: var(--muted);
	}
</style>
