<script lang="ts">
	import type { ComponentHealth } from '$lib/api/types';

	let { components }: { components: ComponentHealth[] } = $props();

	const color = (s: ComponentHealth['status']) =>
		s === 'HEALTHY' ? 'var(--ok)' : s === 'DEGRADED' ? 'var(--sev-medium)' : 'var(--sev-critical)';
</script>

<table>
	<thead>
		<tr>
			<th>Component</th><th>Status</th><th>Latency</th><th>Detail</th>
		</tr>
	</thead>
	<tbody>
		{#each components as c (c.component)}
			<tr>
				<td>{c.component}</td>
				<td><span class="badge" style:--c={color(c.status)}>{c.status}</span></td>
				<td class="num">{c.latency_ms == null ? '—' : `${c.latency_ms} ms`}</td>
				<td class="detail">{c.detail ?? ''}</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	th,
	td {
		text-align: left;
		padding: 0.4rem 0.6rem;
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
	.detail {
		color: var(--muted);
		font-size: 0.78rem;
	}
	.badge {
		display: inline-block;
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
		border: 1px solid var(--c);
		color: var(--c);
	}
</style>
