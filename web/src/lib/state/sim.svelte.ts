// Shared reactive state — a class with $state fields, module singleton (per
// FrontendImplementation §2). API responses are replaced by assignment on refetch.

import { api } from '$lib/api/client';
import type { Alert, Recommendation, SimState } from '$lib/api/types';

class SimStateStore {
	state = $state<SimState | null>(null);
	alerts = $state<Alert[]>([]);
	recommendations = $state<Recommendation[]>([]);

	/** true while the backend reports stale simulator data — drives the global banner */
	isStale = $derived(this.state?.is_stale ?? false);

	refreshState = async () => {
		this.state = await api.state();
	};

	refreshAlerts = async () => {
		this.alerts = await api.alerts();
	};

	refreshRecommendations = async () => {
		this.recommendations = await api.recommendations();
	};

	async approve(id: number) {
		await api.approve(id);
		await this.refreshRecommendations();
	}

	async reject(id: number, note: string) {
		await api.reject(id, note);
		await this.refreshRecommendations();
	}
}

export const sim = new SimStateStore();
