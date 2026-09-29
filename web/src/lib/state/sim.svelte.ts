// Shared reactive state — a class with $state fields, module singleton (per
// FrontendImplementation §2). API responses are replaced by assignment on refetch.

import { api } from '$lib/api/client';
import type { Allocation, Alert, Decision, DemandRow, Forecast, HealthReport, LogEntry, Recommendation, SimState } from '$lib/api/types';

class SimStateStore {
	state = $state<SimState | null>(null);
	alerts = $state<Alert[]>([]);
	recommendations = $state<Recommendation[]>([]);
	allocations = $state<Allocation[]>([]);
	decisions = $state<Decision[]>([]);
	health = $state<HealthReport | null>(null);
	logs = $state<LogEntry[]>([]);
	forecasts = $state<Forecast[]>([]);
	demandRows = $state<DemandRow[]>([]);

	/** true while the backend reports stale simulator data — drives the global banner */
	isStale = $derived(this.state?.is_stale ?? false);

	refreshState = async () => {
		// World + intelligence panels move together on simulation.tick — allSettled
		// so a failed intel endpoint degrades its own panel, never the world view.
		const [state, forecasts, demand] = await Promise.allSettled([
			api.state(),
			api.forecasts(),
			api.demand()
		]);
		if (state.status === 'fulfilled') this.state = state.value;
		if (forecasts.status === 'fulfilled') this.forecasts = forecasts.value;
		if (demand.status === 'fulfilled') this.demandRows = demand.value;
	};

	refreshAlerts = async () => {
		this.alerts = await api.alerts();
	};

	ackAlert = async (id: number) => {
		await api.ackAlert(id);
		await this.refreshAlerts();
	};

	refreshRecommendations = async () => {
		this.recommendations = await api.recommendations();
	};

	refreshAllocations = async () => {
		const history = await api.history();
		this.allocations = history.allocations;
	};

	refreshHistory = async () => {
		const history = await api.history();
		this.decisions = history.decisions;
		this.allocations = history.allocations;
	};

	refreshHealth = async () => {
		this.health = await api.health();
	};

	refreshLogs = async () => {
		this.logs = await api.logs();
	};

	async approve(id: number) {
		await api.approve(id);
		await Promise.all([this.refreshRecommendations(), this.refreshAllocations()]);
	}

	async reject(id: number, note: string) {
		await api.reject(id, note);
		await Promise.all([this.refreshRecommendations(), this.refreshAllocations()]);
	}
}

export const sim = new SimStateStore();
