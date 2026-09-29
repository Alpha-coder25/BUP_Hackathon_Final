// Typed API client for our FastAPI backend (:8080) — TRD §6 with real backend
// shapes (Phase 0/1). Never talks to the simulator directly (SystemArchitecture §4).
// Raw payloads are normalized here so screens consume one stable shape.

import { env } from '$env/dynamic/public';
import {
	ApiError,
	type Alert,
	type Allocation,
	type Decision,
	type DemandRow,
	type Depot,
	type Forecast,
	type HealthReport,
	type LogEntry,
	type Recommendation,
	type Route,
	type SimEvent,
	type SimState,
	type Station,
	type SupplyArrival,
	type Region
} from './types';

// Dynamic public env: runtime-configurable (docker-compose sets PUBLIC_API_BASE
// per environment — no rebuild needed). Falls back to the local default.
function apiBase() {
	return env.PUBLIC_API_BASE ?? 'http://localhost:8080';
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 6000): Promise<T> {
	let res: Response;
	try {
		// Hard timeout — a slow/hanging endpoint (e.g. a backend probe without its
		// own timeout) must degrade the panel, never hang the shell.
		res = await fetch(`${apiBase()}${path}`, {
			...init,
			signal: AbortSignal.timeout(timeoutMs)
		});
	} catch (e) {
		throw new ApiError(0, e instanceof Error && e.name === 'TimeoutError' ? 'TIMEOUT' : 'UNREACHABLE', 'Backend API unreachable');
	}
	if (!res.ok) {
		let code = 'UNKNOWN';
		let message = `HTTP ${res.status}`;
		try {
			const body = await res.json();
			code = body?.detail?.code ?? code;
			message = body?.detail?.message ?? body?.detail ?? message;
		} catch {
			// non-JSON error body — keep the HTTP status message
		}
		throw new ApiError(res.status, code, String(message));
	}
	return res.json() as Promise<T>;
}

// ---- normalizers (backend raw → UI shape) ----

function normalizeState(raw: Record<string, unknown>): SimState {
	const arrivals = (raw.supply_arrivals ?? raw.arrivals ?? []) as SupplyArrival[];
	return {
		is_stale: Boolean(raw.is_stale),
		tick: typeof raw.tick === 'number' ? raw.tick : null,
		depots: (raw.depots ?? []) as Depot[],
		stations: (raw.stations ?? []) as Station[],
		routes: (raw.routes ?? []) as Route[],
		regions: (raw.regions ?? []) as Region[],
		arrivals,
		events: (raw.events ?? []) as SimEvent[],
		metrics: (raw.metrics ?? null) as SimState['metrics']
	};
}

function normalizeHealth(raw: {
	components: Record<string, { status: string; latency_ms?: number; detail?: unknown }>;
}): HealthReport {
	const STATUS = ['HEALTHY', 'DEGRADED', 'DOWN'] as const;
	const components = Object.entries(raw.components ?? {}).map(([component, c]) => ({
		component,
		status: (STATUS.includes(c.status as never) ? c.status : 'DOWN') as 'HEALTHY' | 'DEGRADED' | 'DOWN',
		latency_ms: c.latency_ms ?? null,
		detail: c.detail == null ? null : typeof c.detail === 'string' ? c.detail : JSON.stringify(c.detail),
		checked_at: new Date().toISOString()
	}));
	const worst = components.some((c) => c.status === 'DOWN')
		? 'DOWN'
		: components.some((c) => c.status === 'DEGRADED')
			? 'DEGRADED'
			: components.length > 0
				? 'HEALTHY'
				: 'DOWN';
	return { status: worst, components };
}

export const api = {
	state: async () => normalizeState(await request<Record<string, unknown>>('/api/state')),
	alerts: async () => (await request<Alert[]>('/api/alerts')) ?? [],
	recommendations: async () => (await request<Recommendation[]>('/api/recommendations')) ?? [],
	approve: (id: number) =>
		request<{ ok: true }>(`/api/recommendations/${id}/approve`, { method: 'POST' }),
	reject: (id: number, note: string) =>
		request<{ ok: true }>(`/api/recommendations/${id}/reject`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ note })
		}),
	ackAlert: (id: number) => request<{ ok: true }>(`/api/alerts/${id}/ack`, { method: 'POST' }),
	history: async () => {
		const h = await request<{ decisions: Decision[]; allocations: Allocation[] }>('/api/history');
		return {
			decisions: h?.decisions ?? [],
			allocations: h?.allocations ?? []
		};
	},
	health: async () => normalizeHealth(await request('/health', undefined, 4000)),
	logs: async () => (await request<LogEntry[]>('/api/logs')) ?? [],
	forecasts: async () => (await request<Forecast[]>('/api/forecasts')) ?? [],
	demand: async () => (await request<DemandRow[]>('/api/demand')) ?? []
};
