import type { LayoutLoad } from './$types';
import { api } from '$lib/api/client';

export const load: LayoutLoad = async ({ fetch }) => {
	// First-paint data for the global chrome (health badge, stale banner) and Overview.
	// Individual failures must not block the shell — the dashboard degrades per-panel.
	const [state, alerts, health] = await Promise.allSettled([
		api.state(),
		api.alerts(),
		api.health()
	]);

	return {
		state: state.status === 'fulfilled' ? state.value : null,
		alerts: alerts.status === 'fulfilled' ? alerts.value : [],
		health: health.status === 'fulfilled' ? health.value : null
	};
};
