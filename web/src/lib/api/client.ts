// Typed API client for our FastAPI backend (:8080) — TRD §6.
// Never talks to the simulator directly (SystemArchitecture §4 boundary).

import { PUBLIC_API_BASE } from '$env/static/public';
import { ApiError, type Alert, type Allocation, type Decision, type HealthReport, type Recommendation, type SimState } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let res: Response;
	try {
		res = await fetch(`${PUBLIC_API_BASE}${path}`, init);
	} catch {
		throw new ApiError(0, 'UNREACHABLE', 'Backend API unreachable');
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

export const api = {
	state: () => request<SimState>('/api/state'),
	alerts: () => request<Alert[]>('/api/alerts'),
	ackAlert: (id: number) => request<{ ok: true }>(`/api/alerts/${id}/ack`, { method: 'POST' }),
	recommendations: () => request<Recommendation[]>('/api/recommendations'),
	approve: (id: number) =>
		request<{ ok: true }>(`/api/recommendations/${id}/approve`, { method: 'POST' }),
	reject: (id: number, note: string) =>
		request<{ ok: true }>(`/api/recommendations/${id}/reject`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ note })
		}),
	history: () => request<{ decisions: Decision[]; allocations: Allocation[] }>('/api/history'),
	health: () => request<HealthReport>('/health')
};
