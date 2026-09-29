import type { LayoutLoad } from './$types';
import { api } from '$lib/api/client';

export const load: LayoutLoad = async ({ fetch }) => {
	// First-paint data for the whole dashboard: every screen seeds from the shell
	// load; SSE owns updates afterwards. Individual failures must not block the
	// shell — the dashboard degrades per-panel.
	const [state, alerts, recs, history, health] = await Promise.allSettled([
		api.state(),
		api.alerts(),
		api.recommendations(),
		api.history(),
		api.health()
	]);

	return {
		state: state.status === 'fulfilled' ? state.value : null,
		alerts: alerts.status === 'fulfilled' ? alerts.value : [],
		recommendations: recs.status === 'fulfilled' ? recs.value : [],
		history: history.status === 'fulfilled' ? history.value : { decisions: [], allocations: [] },
		health: health.status === 'fulfilled' ? health.value : null
	};
};
