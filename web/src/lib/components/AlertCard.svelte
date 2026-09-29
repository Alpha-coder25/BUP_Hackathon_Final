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
		border: 1px solid var(--line);
		border-left: 3px solid var(--sev);
		border-radius: 8px;
		padding: 0.75rem 1rem;
		background: var(--panel);
		display: grid;
		gap: 0.4rem;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		font-size: 0.78rem;
	}
	.sev {
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--sev);
	}
	.cause {
		text-transform: uppercase;
		font-size: 0.68rem;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 0.05rem 0.45rem;
	}
	.where {
		font-weight: 600;
	}
	.tick {
		margin-left: auto;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.message {
		margin: 0;
		font-size: 0.9rem;
	}
	.explanation {
		margin: 0;
		font-size: 0.8rem;
		color: var(--muted);
		border-top: 1px dashed var(--line);
		padding-top: 0.4rem;
	}
	footer {
		display: flex;
		align-items: center;
		gap: 0.9rem;
		font-size: 0.8rem;
	}
	button {
		background: none;
		border: 1px solid var(--line);
		border-radius: 6px;
		color: var(--text);
		padding: 0.2rem 0.7rem;
		cursor: pointer;
		font-size: 0.8rem;
	}
	button:hover:not(:disabled) {
		border-color: var(--text);
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.acked {
		color: var(--muted);
		letter-spacing: 0.04em;
		font-size: 0.72rem;
	}
	footer a {
		margin-left: auto;
		color: var(--muted);
		text-decoration: none;
	}
	footer a:hover {
		color: var(--text);
	}
</style>
