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

<article class="card" id="rec-{rec.id}" style:--policy={rec.policy === 'optimizer' ? 'var(--ok)' : rec.policy === 'heuristic' ? 'var(--sev-medium)' : 'var(--sev-critical)'}>
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
