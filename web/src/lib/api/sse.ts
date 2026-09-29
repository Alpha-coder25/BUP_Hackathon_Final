// SSE live refresh — events are hints, not data: every event triggers a re-GET
// of the affected endpoint(s) only (FrontendImplementation §2, build order step 4).
// EventSource reconnects on its own; this helper adds the 30 s polling fallback
// while the stream is down and a full refetch on reconnect.

import { PUBLIC_API_BASE } from '$env/static/public';
import { sim } from '$lib/state/sim.svelte';

export function startLiveRefresh(): () => void {
	const es = new EventSource(`${PUBLIC_API_BASE}/api/stream`);
	let poll: ReturnType<typeof setInterval> | null = null;

	function refreshAffected(events: string[]) {
		const jobs = new Set<Promise<unknown>>();
		for (const event of events) {
			switch (event) {
				case 'simulation.tick':
				case 'inventory.updated':
					jobs.add(sim.refreshState());
					break;
				case 'alert.raised':
				case 'alert.acknowledged':
					jobs.add(sim.refreshAlerts());
					break;
				case 'recommendation.created':
				case 'recommendation.decided':
					jobs.add(sim.refreshRecommendations());
					break;
				case 'allocation.status_changed':
					// Status flips also change recommendation-level progress.
					jobs.add(sim.refreshAllocations());
					jobs.add(sim.refreshRecommendations());
					break;
				default:
					// Unknown event — cheap safety net: refresh the world.
					jobs.add(sim.refreshState());
			}
		}
		for (const job of jobs) job.catch(() => {});
	}

	function startPolling() {
		if (poll) return;
		poll = setInterval(() => {
			sim.refreshState().catch(() => {});
			sim.refreshAlerts().catch(() => {});
			sim.refreshRecommendations().catch(() => {});
			sim.refreshAllocations().catch(() => {});
		}, 30_000);
	}

	function stopPolling() {
		if (!poll) return;
		clearInterval(poll);
		poll = null;
	}

	async function refetchAll() {
		stopPolling(); // stream is back — full refetch then stop polling
		await Promise.allSettled([
			sim.refreshState(),
			sim.refreshAlerts(),
			sim.refreshRecommendations(),
			sim.refreshAllocations()
		]);
	}

	// Named SSE events → targeted refetch. The backend forwards the simulator's
	// event names plus its own alert/recommendation notifications.
	for (const name of [
		'simulation.tick',
		'inventory.updated',
		'alert.raised',
		'alert.acknowledged',
		'recommendation.created',
		'recommendation.decided',
		'allocation.status_changed'
	]) {
		es.addEventListener(name, () => refreshAffected([name]));
	}

	// Any other named event → safety-net world refresh (covers `simulator.notice` etc.)
	es.onmessage = () => refreshAffected(['unknown']);

	es.onopen = () => void refetchAll();
	es.onerror = () => startPolling();

	void refetchAll(); // initial fetch
	return () => {
		es.close();
		stopPolling();
	};
}
