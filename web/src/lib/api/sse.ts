// SSE live refresh — events are hints, not data: every event triggers a re-GET
// of the affected endpoints. EventSource reconnects on its own; this helper only
// adds the 30 s polling fallback while the stream is down (FrontendImplementation §2).

import { PUBLIC_API_BASE } from '$env/static/public';
import { sim } from '$lib/state/sim.svelte';

export function startLiveRefresh(): () => void {
	const es = new EventSource(`${PUBLIC_API_BASE}/api/stream`);
	let poll: ReturnType<typeof setInterval> | null = null;

	function startPolling() {
		if (poll) return;
		poll = setInterval(() => {
			sim.refreshState().catch(() => {});
			sim.refreshAlerts().catch(() => {});
			sim.refreshRecommendations().catch(() => {});
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
			sim.refreshRecommendations()
		]);
	}

	es.onopen = () => void refetchAll();
	es.onerror = () => startPolling();

	void refetchAll(); // initial fetch
	return () => {
		es.close();
		stopPolling();
	};
}
