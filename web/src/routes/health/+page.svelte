<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import HealthTable from '$lib/components/HealthTable.svelte';
	import LogViewer from '$lib/components/LogViewer.svelte';

	let tab = $state<'components' | 'logs'>('components');

	// Health polls at the layout level; the Logs tab only refetches while viewed.
	$effect(() => {
		if (tab !== 'logs') return;
		sim.refreshLogs().catch(() => {});
		const poll = setInterval(() => sim.refreshLogs().catch(() => {}), 5_000);
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
		font-size: var(--text-2xl);
		margin: 0 0 var(--space-7);
	}
	.tabs {
		display: flex;
		gap: var(--space-5);
		margin-bottom: var(--space-8);
	}
	.tabs button {
		background: transparent;
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		color: var(--text-tertiary);
		padding: var(--space-3) var(--space-8);
		font-size: var(--text-md);
		font-family: inherit;
		cursor: pointer;
		transition: border-color var(--motion-instant) ease, background var(--motion-instant) ease, color var(--motion-instant) ease;
	}
	.tabs button:hover {
		color: var(--text-primary);
		border-color: var(--text-tertiary);
	}
	.tabs button.active {
		color: var(--text-inverse);
		border-color: var(--border-default);
		background: var(--surface-strong);
	}
	.fallback {
		margin-top: var(--space-7);
		color: var(--sev-medium);
		font-size: var(--text-md);
	}
	.empty {
		color: var(--text-secondary);
	}
</style>
