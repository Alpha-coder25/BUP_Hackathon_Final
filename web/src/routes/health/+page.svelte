<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import HealthTable from '$lib/components/HealthTable.svelte';
	import LogViewer from '$lib/components/LogViewer.svelte';

	let tab = $state<'components' | 'logs'>('components');

	// Health probes every 5s per BackendImplementation §8; logs refresh alongside.
	$effect(() => {
		const tick = () => {
			sim.refreshHealth().catch(() => {});
			sim.refreshLogs().catch(() => {});
		};
		tick();
		const poll = setInterval(tick, 5_000);
		return () => clearInterval(poll);
	});

	const fallbackActive = $derived(
		(sim.health?.components ?? []).some(
			(c) => c.status !== 'HEALTHY' && (c.component === 'forecaster' || c.component === 'planner')
		)
	);
</script>

<h1>Health</h1>

<div class="tabs" role="tablist">
	<button role="tab" aria-selected={tab === 'components'} class:active={tab === 'components'} onclick={() => (tab = 'components')}>
		Components
	</button>
	<button role="tab" aria-selected={tab === 'logs'} class:active={tab === 'logs'} onclick={() => (tab = 'logs')}>
		Logs
	</button>
</div>

{#if tab === 'components'}
	{#if sim.health === null}
		<p class="empty">No health signal — is the backend API up on :8080?</p>
	{:else}
		<HealthTable components={sim.health.components} />
		{#if fallbackActive}
			<p class="fallback" role="alert">Fallback active — a decision/forecast component is degraded; recommendations may be heuristic.</p>
		{/if}
	{/if}
{:else}
	<LogViewer logs={sim.logs} />
{/if}

<style>
	h1 {
		font-size: 1.25rem;
		margin: 0 0 0.75rem;
	}
	.tabs {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.9rem;
	}
	.tabs button {
		background: none;
		border: 1px solid var(--line);
		border-radius: 999px;
		color: var(--muted);
		padding: 0.25rem 0.9rem;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.tabs button.active {
		color: var(--text);
		border-color: var(--text);
	}
	.fallback {
		margin-top: 0.75rem;
		color: var(--sev-medium);
		font-size: 0.82rem;
	}
	.empty {
		color: var(--muted);
	}
</style>
