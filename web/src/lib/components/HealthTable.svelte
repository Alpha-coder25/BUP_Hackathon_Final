<script lang="ts">
	import type { ComponentHealth } from '$lib/api/types';

	let { components }: { components: ComponentHealth[] } = $props();

	const color = (s: ComponentHealth['status']) =>
		s === 'HEALTHY' ? 'var(--color-ok)' : s === 'DEGRADED' ? 'var(--sev-medium)' : 'var(--sev-critical)';
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
		font-size: var(--text-lg);
	}
	th,
	td {
		text-align: left;
		padding: var(--space-4) var(--space-6);
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
	.detail {
		color: var(--text-tertiary);
		font-size: var(--text-md);
	}
	.badge {
		display: inline-block;
		font-size: var(--text-sm);
		font-weight: 600;
		letter-spacing: 0.04em;
		padding: var(--space-1) var(--space-5);
		border-radius: var(--radius-sm);
		border: var(--space-1) solid var(--c);
		color: var(--c);
	}
</style>
