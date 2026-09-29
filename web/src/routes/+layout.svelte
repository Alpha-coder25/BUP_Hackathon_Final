<script lang="ts">
	import '../app.css';
	import type { Snippet } from 'svelte';
import type { LayoutData } from './$types';
	import { sim } from '$lib/state/sim.svelte';
	import { startLiveRefresh } from '$lib/api/sse';
import { PUBLIC_API_BASE } from '$env/static/public';
import { resolve } from '$app/paths';

let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// Seed the store from the server load, then take over with live refresh.
	// Health polls every 5s at the shell level so the top-bar badge is live on
	// every screen (build order step 4).
	$effect(() => {
		if (data?.state) sim.state = data.state;
		if (data?.alerts) sim.alerts = data.alerts;
		if (data?.health) sim.health = data.health;

		const healthPoll = setInterval(() => sim.refreshHealth().catch(() => {}), 5_000);
		const stopRefresh = startLiveRefresh();
		return () => {
			stopRefresh();
			clearInterval(healthPoll);
		};
	});

	type RoutePath = Parameters<typeof resolve>[0];

const nav: { href: RoutePath; label: string }[] = [
		{ href: '/', label: 'Overview' },
		{ href: '/alerts', label: 'Alerts' },
		{ href: '/recommendations', label: 'Recommendations' },
		{ href: '/history', label: 'History' },
		{ href: '/health', label: 'Health' }
	];

	// Top-bar badge from real /health — DOWN/DEGRADED/unknown all break the green.
	const healthClass = $derived(
		sim.health === null ? 'down' : sim.health.status === 'HEALTHY' ? 'ok' : 'warn'
	);
	const healthLabel = $derived(
		sim.health === null ? 'No signal' : sim.health.status.charAt(0) + sim.health.status.slice(1).toLowerCase()
	);
</script>

<div class="shell">
	<header>
		<span class="brand">Fuel Ops</span>
		<nav>
			{#each nav as item (item.href)}
				<a href={resolve(item.href)}>{item.label}</a>
			{/each}
		</nav>
		<span class="tick" title="Simulation tick">T{sim.state?.tick ?? '—'}</span>
		<a class="badge" href={resolve('/health')} style:--c={healthClass === 'ok' ? 'var(--ok)' : healthClass === 'warn' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
			{healthLabel}
		</a>
	</header>

	{#if sim.isStale}
		<div class="stale" role="alert">
			Stale data — collector degraded. Values may be out of date; approvals paused.
		</div>
	{/if}

	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(:root) {
		--bg: #0e1116;
		--panel: #161b23;
		--line: #262e3a;
		--text: #e6e9ee;
		--muted: #8b95a5;
		--ok: #3fb96f;
		--sev-low: #8b95a5;
		--sev-medium: #d9a13b;
		--sev-high: #e07b39;
		--sev-critical: #e5484d;
	}
	:global(body) {
		margin: 0;
		background: var(--bg);
		color: var(--text);
		font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
	}
	.shell {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}
	header {
		display: flex;
		align-items: center;
		gap: 1.25rem;
		padding: 0.6rem 1.25rem;
		border-bottom: 1px solid var(--line);
	}
	.brand {
		font-weight: 700;
		letter-spacing: 0.02em;
	}
	nav {
		display: flex;
		gap: 0.9rem;
	}
	nav a {
		color: var(--muted);
		text-decoration: none;
		font-size: 0.9rem;
	}
	nav a:hover {
		color: var(--text);
	}
	.tick {
		margin-left: auto;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.badge {
		font-size: 0.75rem;
		font-weight: 600;
		text-decoration: none;
		padding: 0.15rem 0.6rem;
		border-radius: 999px;
		border: 1px solid var(--c);
		color: var(--c);
	}
	.stale {
		background: var(--sev-medium);
		color: #1a1a1a;
		font-size: 0.85rem;
		font-weight: 600;
		padding: 0.4rem 1.25rem;
	}
	main {
		flex: 1;
		padding: 1.25rem;
		max-width: 1200px;
		width: 100%;
		margin: 0 auto;
		box-sizing: border-box;
	}
</style>
