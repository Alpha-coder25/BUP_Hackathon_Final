<script lang="ts">
	import { fmtHours, severityVar } from '$lib/format';
	import { sim } from '$lib/state/sim.svelte';
	import type { Alert } from '$lib/api/types';
	import { resolve } from '$app/paths';

	let { alert }: { alert: Alert } = $props();

	let acking = $state(false);

	const CAUSE_TAG: Record<Alert['type'], string> = {
		shortage: 'shortage',
		anomaly: 'spike',
		disruption: 'route',
		system: 'system'
	};

	async function ack() {
		acking = true;
		try {
			await sim.ackAlert(alert.id);
		} finally {
			acking = false;
		}
	}
</script>

<article class="card" style:--sev={severityVar(alert.severity)}>
	<header>
		<span class="sev">{alert.severity}</span>
		<span class="cause">{CAUSE_TAG[alert.type] ?? alert.type}</span>
		<span class="where">{alert.station_id} · {alert.fuel_type}</span>
		<span class="tick">T{alert.created_tick}</span>
	</header>

	<p class="message">{alert.message}</p>

	{#if alert.explanation}
		<p class="explanation">{alert.explanation}</p>
	{/if}

	<footer>
		{#if alert.status === 'OPEN'}
			<button onclick={ack} disabled={acking}>{acking ? 'Acking…' : 'Ack'}</button>
		{:else}
			<span class="acked">ACKED</span>
		{/if}
		<a href="{resolve('/recommendations')}#rec-{alert.id}">View recommendation →</a>
	</footer>
</article>

<style>
	.card {
		border: var(--space-1) solid var(--border-muted);
		border-left: 3px solid var(--sev);
		border-radius: var(--radius-sm);
		padding: var(--space-7) var(--space-8);
		background: var(--surface-raised);
		box-shadow: var(--shadow-1);
		display: grid;
		gap: var(--space-4);
	}
	header {
		display: flex;
		align-items: baseline;
		gap: var(--space-6);
		font-size: var(--text-md);
	}
	.sev {
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--sev);
	}
	.cause {
		text-transform: uppercase;
		font-size: var(--text-xs);
		color: var(--text-secondary);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-4);
	}
	.where {
		font-weight: 600;
	}
	.tick {
		margin-left: auto;
		color: var(--text-secondary);
		font-variant-numeric: tabular-nums;
	}
	.message {
		margin: 0;
		font-size: var(--text-lg);
	}
	.explanation {
		margin: 0;
		font-size: var(--text-md);
		color: var(--text-tertiary);
		border-top: var(--space-1) dashed var(--border-muted);
		padding-top: var(--space-4);
	}
	footer {
		display: flex;
		align-items: center;
		gap: var(--space-7);
		font-size: var(--text-md);
	}
	button {
		background: transparent;
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		color: var(--text-primary);
		padding: var(--space-3) var(--space-7);
		cursor: pointer;
		font-size: var(--text-md);
		font-family: inherit;
		transition: border-color var(--motion-instant) ease, background var(--motion-instant) ease;
	}
	button:hover:not(:disabled) {
		border-color: var(--text-tertiary);
		background: var(--surface-strong);
	}
	button:active:not(:disabled) {
		background: var(--surface-muted);
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.acked {
		color: var(--text-secondary);
		letter-spacing: 0.04em;
		font-size: var(--text-sm);
	}
	footer a {
		margin-left: auto;
		color: var(--text-tertiary);
		text-decoration: none;
		border-radius: var(--radius-xs);
	}
	footer a:hover {
		color: var(--text-primary);
	}
</style>
