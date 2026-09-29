<script lang="ts">
	import '../app.css';
	import type { Snippet } from 'svelte';
import type { LayoutData } from './$types';
	import { sim } from '$lib/state/sim.svelte';
	import { startLiveRefresh } from '$lib/api/sse';
import { resolve } from '$app/paths';
import { page } from '$app/state';

let { children, data }: { children: Snippet; data: LayoutData } = $props();

	// Seed the store synchronously from the server load (works during SSR — no
	// $effect gating), then attach live refresh + health polling as client effects.
	// Deliberately reads the initial load value only — SSE owns updates afterwards.
	/* svelte-ignore state_referenced_locally */
	sim.state = data?.state ?? sim.state;
	/* svelte-ignore state_referenced_locally */
	sim.alerts = data?.alerts ?? sim.alerts;
	/* svelte-ignore state_referenced_locally */
	sim.recommendations = data?.recommendations ?? sim.recommendations;
	/* svelte-ignore state_referenced_locally */
	sim.decisions = data?.history?.decisions ?? sim.decisions;
	/* svelte-ignore state_referenced_locally */
	sim.allocations = data?.history?.allocations ?? sim.allocations;
	/* svelte-ignore state_referenced_locally */
	sim.health = data?.health ?? sim.health;
	/* svelte-ignore state_referenced_locally */
	sim.forecasts = data?.forecasts ?? sim.forecasts;
	/* svelte-ignore state_referenced_locally */
	sim.demandRows = data?.demand ?? sim.demandRows;

	$effect(() => {
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

	// Keyboard-first nav: current route is marked with aria-current (plus
	// .active styling that depends on the route, not the hover state).
	const isActive = (href: RoutePath) => page.url.pathname === resolve(href);

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
		<span class="brand">FUELINTEL</span>
		<span class="brand-sub">Fuel Supply Intelligence &amp; Resilience Platform</span>
		<nav aria-label="Primary">
			{#each nav as item (item.href)}
				<a
					href={resolve(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
					class:active={isActive(item.href)}
				>{item.label}</a>
			{/each}
		</nav>
		<span class="tick" title="Simulation tick">T{sim.state?.tick ?? '—'}</span>
		<a class="badge" href={resolve('/health')} style:--c={healthClass === 'ok' ? 'var(--color-ok)' : healthClass === 'warn' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
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
	/*
	 * FUELINTEL design tokens — Fuel Supply Intelligence & Resilience Platform.
	 * Single source of truth for surfaces, text, borders, radius, spacing, type
	 * and motion. Components consume semantic tokens only — never raw hex.
	 */
	:global(:root) {
		/* Surfaces */
		--surface-base: #000000;
		--surface-muted: #0d131b;
		--surface-raised: #0a0f16;
		--surface-strong: #111823;

		/* Text */
		--text-primary: #dde5ee;
		--text-secondary: #5c6f85;
		--text-tertiary: #8496ab;
		--text-inverse: #f2f6fa;

		/* Borders */
		--border-default: #e5e7eb;
		--border-muted: #1a2432;

		/* Status + severity (AA-checked on dark surfaces) */
		--color-ok: #4ade80;
		--sev-low: #8496ab;
		--sev-medium: #eab308;
		--sev-high: #fb923c;
		--sev-critical: #f87171;

		/* Typography */
		--font-primary: 'Inter', ui-sans-serif, system-ui, sans-serif;
		--font-mono: ui-monospace, 'Cascadia Code', Menlo, monospace;
		--text-xs: 0.5625rem; /* 9px */
		--text-sm: 0.6875rem; /* 11px */
		--text-md: 0.75rem; /* 12px */
		--text-lg: 0.875rem; /* 14px */
		--text-xl: 1rem; /* 16px */
		--text-2xl: 1.125rem; /* 18px */

		/* Spacing (space.1..space.8) */
		--space-1: 1px;
		--space-2: 2px;
		--space-3: 4px;
		--space-4: 6px;
		--space-5: 8px;
		--space-6: 10px;
		--space-7: 12px;
		--space-8: 14px;

		/* Radius */
		--radius-xs: 2px;
		--radius-sm: 4px;

		/* Elevation: subtle top inset light + soft drop (shadow.1) */
		--shadow-1:
			rgba(0, 0, 0, 0) 0px 0px 0px 0px,
			rgba(0, 0, 0, 0) 0px 0px 0px 0px,
			rgba(255, 255, 255, 0.03) 0px 1px 0px 0px inset,
			rgba(0, 0, 0, 0.5) 0px 6px 16px -8px;

		/* Motion */
		--motion-instant: 150ms;
		--motion-fast: 200ms;
	}
	:global(body) {
		margin: 0;
		background: var(--surface-base);
		color: var(--text-primary);
		font-family: var(--font-primary);
		font-size: var(--text-xl);
		font-weight: 400;
		line-height: 1.5;
	}
	/* Keyboard-first: visible focus ring on every interactive element. */
	:global(:focus-visible) {
		outline: var(--space-2) solid var(--border-default);
		outline-offset: var(--space-2);
	}
	.shell {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-8);
		padding: var(--space-7) var(--space-8);
		border-bottom: var(--space-1) solid var(--border-muted);
		background: var(--surface-raised);
		box-shadow: var(--shadow-1);
	}
	.brand {
		font-weight: 700;
		font-size: var(--text-2xl);
		letter-spacing: 0.04em;
		color: var(--text-inverse);
	}
	.brand-sub {
		font-size: var(--text-md);
		color: var(--text-secondary);
		/* Long-content handling: drop the tagline before crowding the nav. */
		@media (max-width: 900px) {
			display: none;
		}
	}
	nav {
		display: flex;
		gap: var(--space-6);
	}
	nav a {
		color: var(--text-tertiary);
		text-decoration: none;
		font-size: var(--text-lg);
		border-radius: var(--radius-xs);
		padding: var(--space-2) var(--space-3);
		transition: color var(--motion-instant) ease;
	}
	nav a:hover {
		color: var(--text-primary);
	}
	nav a[aria-current='page'],
	nav a.active {
		color: var(--text-inverse);
	}
	.tick {
		margin-left: auto;
		color: var(--text-tertiary);
		font-size: var(--text-md);
		font-variant-numeric: tabular-nums;
	}
	.badge {
		font-size: var(--text-md);
		font-weight: 600;
		text-decoration: none;
		padding: var(--space-1) var(--space-6);
		border-radius: var(--radius-sm);
		border: var(--space-1) solid var(--c);
		color: var(--c);
		transition: border-color var(--motion-instant) ease;
	}
	.badge:hover {
		border-color: var(--border-default);
	}
	.stale {
		background: var(--sev-medium);
		color: var(--surface-base);
		font-size: var(--text-md);
		font-weight: 600;
		padding: var(--space-4) var(--space-8);
	}
	main {
		flex: 1;
		padding: var(--space-8);
		max-width: 1200px;
		width: 100%;
		margin: 0 auto;
		box-sizing: border-box;
	}
</style>
