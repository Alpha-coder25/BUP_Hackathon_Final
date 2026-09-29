<script lang="ts">
	import { sim } from '$lib/state/sim.svelte';
	import { policyLabel } from '$lib/format';
	import type { Recommendation } from '$lib/api/types';
	import { resolve } from '$app/paths';

	let { rec }: { rec: Recommendation } = $props();

	let note = $state('');
	let showNote = $state(false);
	let busy = $state(false);
	// Set while an approve/reject round-trip is in flight — UI must not double-submit
	// even though the idempotency key makes retries safe (FrontendImplementation §4).
	let error = $state<string | null>(null);
	let approvedItemIds = $state<number[]>([]);

	const isHumanReview = $derived(rec.policy === 'fallback' || rec.confidence < 0.6);
	const isProposed = $derived(rec.status === 'PROPOSED');
	const canDecide = $derived(isProposed && !busy && !sim.isStale);

	const pct = (n: number) => `${Math.round(n * 100)}%`;

	async function decide(action: 'approve' | 'reject') {
		busy = true;
		error = null;
		try {
			if (action === 'approve') {
				await sim.approve(rec.id);
				// Approve succeeded — show the allocation tracker for this rec's items.
				approvedItemIds = rec.items.map((i) => i.id);
			} else {
				await sim.reject(rec.id, note);
			}
		} catch (e) {
			// 409s from the backend arrive as actionable ApiErrors — show the message inline.
			error = e instanceof Error ? e.message : 'Decision failed';
		} finally {
			busy = false;
		}
	}
</script>

<article class="card" id="rec-{rec.id}" style:--policy={rec.policy === 'optimizer' ? 'var(--color-ok)' : rec.policy === 'heuristic' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
	<header>
		<span class="policy">{policyLabel(rec.policy)}</span>
		{#if isHumanReview}
			<span class="review">Human review requested</span>
		{/if}
		<span class="tick">#{rec.id}</span>
	</header>

	{#each rec.items as item (item.id)}
		<p class="route">
			<strong>{item.depot_id}</strong> → <strong>{item.station_id}</strong>
			· {item.route_id} · {item.fuel_type}
		</p>
		<p class="qty">{item.quantity} L</p>
	{/each}

	<div class="stats">
		<span class="delta">Risk {pct(rec.risk_before)} → <strong>{pct(rec.risk_after)}</strong></span>
		<span class="confidence" title="confidence {pct(rec.confidence)}">
			<span class="confbar" style:--conf="{pct(rec.confidence)}"></span>
			{pct(rec.confidence)}
		</span>
	</div>

	<p class="explanation">{rec.explanation}</p>

	{#if rec.alternatives.length > 0}
		<details>
			<summary>Alternatives ({rec.alternatives.length})</summary>
			<ul>
				{#each rec.alternatives as alt (alt)}
					<li>{alt}</li>
				{/each}
			</ul>
		</details>
	{/if}

	{#if error}
		<p class="error" role="alert">{error}</p>
	{/if}

	{#if isProposed}
		<footer>
			{#if showNote}
				<input placeholder="Rejection note" bind:value={note} />
				<button class="reject" onclick={() => decide('reject')} disabled={!canDecide}>
					{busy ? '…' : 'Confirm reject'}
				</button>
				<button onclick={() => (showNote = false)}>Cancel</button>
			{:else}
				<button class="approve" onclick={() => decide('approve')} disabled={!canDecide}>
					{busy ? 'Submitting…' : 'Approve'}
				</button>
				<button class="reject" onclick={() => (showNote = true)} disabled={!canDecide}>Reject</button>
			{/if}
		</footer>
	{:else}
		<footer><span class="status">{rec.status}</span></footer>
	{/if}

	{#if approvedItemIds.length > 0}
		{@render allocationTracker()}
	{/if}
</article>

{#snippet allocationTracker()}
	<div class="tracker">
		<span class="tracker-label">Allocation</span>
		<AllocationTracker recommendationId={rec.id} />
	</div>
{/snippet}

<script module lang="ts">
	import AllocationTracker from '$lib/components/AllocationTracker.svelte';
</script>

<style>
	/* FUELINTEL card — states: default / hover / focus-visible / active /
	   disabled / loading (busy labels) / error (inline role=alert). */
	.card {
		border: var(--space-1) solid var(--border-muted);
		border-left: 3px solid var(--policy);
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
	.policy {
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--policy);
		font-size: var(--text-sm);
	}
	.review {
		text-transform: uppercase;
		font-size: var(--text-xs);
		color: var(--sev-medium);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-4);
	}
	.tick {
		margin-left: auto;
		color: var(--text-secondary);
		font-variant-numeric: tabular-nums;
	}
	.route {
		margin: 0;
		font-size: var(--text-lg);
	}
	.qty {
		margin: 0;
		font-size: var(--text-lg);
		font-variant-numeric: tabular-nums;
		color: var(--text-inverse);
	}
	.stats {
		display: flex;
		align-items: center;
		gap: var(--space-8);
		font-size: var(--text-md);
		color: var(--text-tertiary);
	}
	.delta strong {
		color: var(--text-primary);
	}
	.confidence {
		display: inline-flex;
		align-items: center;
		gap: var(--space-3);
		font-variant-numeric: tabular-nums;
	}
	.confbar {
		display: inline-block;
		width: 5rem;
		height: var(--space-3);
		border-radius: var(--radius-xs);
		background: var(--surface-strong) linear-gradient(to right, var(--color-ok) var(--conf), transparent var(--conf));
	}
	.explanation {
		margin: 0;
		font-size: var(--text-md);
		color: var(--text-tertiary);
		border-top: var(--space-1) dashed var(--border-muted);
		padding-top: var(--space-4);
	}
	details {
		font-size: var(--text-md);
	}
	summary {
		cursor: pointer;
		color: var(--text-tertiary);
		border-radius: var(--radius-xs);
	}
	summary:hover {
		color: var(--text-primary);
	}
	ul {
		margin: var(--space-3) 0 0;
		padding-left: var(--space-8);
		color: var(--text-secondary);
	}
	.error {
		margin: 0;
		font-size: var(--text-md);
		color: var(--sev-critical);
		border: var(--space-1) solid var(--sev-critical);
		border-radius: var(--radius-sm);
		padding: var(--space-3) var(--space-5);
	}
	footer {
		display: flex;
		align-items: center;
		gap: var(--space-5);
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
	button.approve {
		color: var(--color-ok);
		border-color: var(--color-ok);
	}
	button.approve:hover:not(:disabled) {
		background: var(--surface-strong);
		border-color: var(--color-ok);
	}
	button.reject {
		color: var(--sev-critical);
	}
	input {
		flex: 1;
		background: var(--surface-muted);
		color: var(--text-primary);
		border: var(--space-1) solid var(--border-muted);
		border-radius: var(--radius-sm);
		padding: var(--space-3) var(--space-5);
		font-size: var(--text-md);
		font-family: inherit;
	}
	input:hover {
		border-color: var(--text-tertiary);
	}
	input::placeholder {
		color: var(--text-secondary);
	}
	.status {
		color: var(--text-secondary);
		letter-spacing: 0.04em;
		font-size: var(--text-sm);
		font-weight: 600;
	}
	.tracker {
		border-top: var(--space-1) solid var(--border-muted);
		padding-top: var(--space-4);
	}
	.tracker-label {
		display: block;
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-tertiary);
		margin-bottom: var(--space-3);
	}
</style>
