// Zero-dependency mock of our backend contract (TRD §6 + agreed extensions) for
// offline UI development and smoke tests. NOT part of the app or docker deploy —
// run manually: `node web/mock-backend.mjs` (then start web/ with the mock env).
// The real backend replaces this 1:1; the frontend never knows the difference.

import { createServer } from 'node:http';

const PORT = Number(process.env.MOCK_PORT || 8080);

// ---- deterministic world (mirrors the simulator baseline) ----

const FUELS = ['DIESEL', 'PETROL', 'OCTANE'];

const regions = [
	{ id: 'region-dhaka', name: 'Dhaka Division', demand_factor: 1.0 },
	{ id: 'region-chattogram', name: 'Chattogram Division', demand_factor: 1.08 }
];

const depots = [
	{
		id: 'depot-gazipur', name: 'Gazipur Depot', region_id: 'region-dhaka', status: 'OPEN',
		dispatch_capacity_per_tick: 12000,
		capacity: { DIESEL: 90000, PETROL: 70000, OCTANE: 45000 },
		inventory: { DIESEL: 60000, PETROL: 45000, OCTANE: 26000 }
	},
	{
		id: 'depot-patiya', name: 'Patiya Depot', region_id: 'region-chattogram', status: 'OPEN',
		dispatch_capacity_per_tick: 11000,
		capacity: { DIESEL: 85000, PETROL: 65000, OCTANE: 40000 },
		inventory: { DIESEL: 55000, PETROL: 42000, OCTANE: 24000 }
	}
];

const stations = [
	{
		id: 'station-mirpur', name: 'Mirpur Fuel Station', region_id: 'region-dhaka', status: 'OPEN',
		demand_profile: 'urban_high', demand_multiplier: 1.0,
		capacity: { DIESEL: 15000, PETROL: 14000, OCTANE: 9000 },
		inventory: { DIESEL: 2400, PETROL: 9000, OCTANE: 5000 }
	},
	{
		id: 'station-tongi', name: 'Tongi Fuel Station', region_id: 'region-dhaka', status: 'OPEN',
		demand_profile: 'industrial', demand_multiplier: 1.0,
		capacity: { DIESEL: 18000, PETROL: 9000, OCTANE: 6000 },
		inventory: { DIESEL: 11000, PETROL: 6000, OCTANE: 3500 }
	},
	{
		id: 'station-karnaphuli', name: 'Karnaphuli Fuel Station', region_id: 'region-chattogram', status: 'OPEN',
		demand_profile: 'highway', demand_multiplier: 1.0,
		capacity: { DIESEL: 14000, PETROL: 15000, OCTANE: 9000 },
		inventory: { DIESEL: 8500, PETROL: 9500, OCTANE: 5200 }
	},
	{
		id: 'station-coxsbazar', name: "Cox's Bazar Fuel Station", region_id: 'region-chattogram', status: 'OPEN',
		demand_profile: 'regional', demand_multiplier: 1.0,
		capacity: { DIESEL: 12000, PETROL: 12000, OCTANE: 7000 },
		inventory: { DIESEL: 7500, PETROL: 7500, OCTANE: 4200 }
	}
];

const routes = [
	{ id: 'route-gazipur-mirpur', source_depot_id: 'depot-gazipur', destination_station_id: 'station-mirpur', transit_ticks: 2, max_shipment: 7000, status: 'AVAILABLE' },
	{ id: 'route-gazipur-tongi', source_depot_id: 'depot-gazipur', destination_station_id: 'station-tongi', transit_ticks: 2, max_shipment: 6500, status: 'AVAILABLE' },
	{ id: 'route-patiya-karnaphuli', source_depot_id: 'depot-patiya', destination_station_id: 'station-karnaphuli', transit_ticks: 2, max_shipment: 7000, status: 'AVAILABLE' },
	{ id: 'route-patiya-coxsbazar', source_depot_id: 'depot-patiya', destination_station_id: 'station-coxsbazar', transit_ticks: 3, max_shipment: 6000, status: 'AVAILABLE' },
	{ id: 'route-gazipur-karnaphuli', source_depot_id: 'depot-gazipur', destination_station_id: 'station-karnaphuli', transit_ticks: 4, max_shipment: 5000, status: 'AVAILABLE' },
	{ id: 'route-patiya-mirpur', source_depot_id: 'depot-patiya', destination_station_id: 'station-mirpur', transit_ticks: 4, max_shipment: 5000, status: 'AVAILABLE' }
];

const arrivals = [
	{ id: 'supply-001', depot_id: 'depot-gazipur', fuel_type: 'DIESEL', quantity: 18000, planned_tick: 12, actual_tick: null, status: 'SCHEDULED' },
	{ id: 'supply-002', depot_id: 'depot-patiya', fuel_type: 'PETROL', quantity: 12000, planned_tick: 14, actual_tick: null, status: 'SCHEDULED' },
	{ id: 'supply-003', depot_id: 'depot-gazipur', fuel_type: 'OCTANE', quantity: 6000, planned_tick: 9, actual_tick: null, status: 'DELAYED' }
];

const events = [
	{ id: 1, type: 'demand_spike', start_tick: 8, end_tick: 20, status: 'ACTIVE', parameters: { region_ids: ['region-dhaka'], multiplier: 1.8 } }
];

// ---- mutable state ----

let tick = 14;
let isStale = false;
let nextAlertId = 3;
let nextRecId = 2;
let nextDecisionId = 2;
let nextAllocationId = 2;

const alerts = [
	{
		id: 1, type: 'shortage', severity: 'CRITICAL', station_id: 'station-mirpur', fuel_type: 'DIESEL',
		message: 'Projected stockout in 6.2 hours — inventory 2,400 L vs expected demand 11,900 L.',
		status: 'OPEN', created_tick: 13,
		explanation: 'Mirpur is burning 1.9k L/h after the Dhaka demand spike. Current stock covers roughly 6 hours. A resupply from Gazipur inside the next tick prevents unmet demand.'
	},
	{
		id: 2, type: 'anomaly', severity: 'HIGH', station_id: 'station-tongi', fuel_type: 'DIESEL',
		message: 'Demand spike: latest tick is 3.2σ above the rolling mean.',
		status: 'OPEN', created_tick: 14,
		explanation: 'Industrial profile demand jumped sharply against a stable baseline. The z-score exceeds the anomaly threshold. Watch for sustained elevation before reallocating.'
	}
];

const recommendations = [
	{
		id: 1, status: 'PROPOSED', policy: 'optimizer', confidence: 0.42,
		risk_before: 0.72, risk_after: 0.19, expires_tick: 20,
		explanation: 'Shipment of 5,000 L diesel from Gazipur covers the 6-hour gap with margin. Risk falls from 72% to 19%. Low confidence reflects thin demand history during the spike.',
		alternatives: ['5,000 L via route-patiya-mirpur (4 ticks transit, arrives too late)', 'Split 2,500 L now + 2,500 L next tick'],
		items: [{ id: 1, depot_id: 'depot-gazipur', station_id: 'station-mirpur', route_id: 'route-gazipur-mirpur', fuel_type: 'DIESEL', quantity: 5000 }]
	}
];

const decisions = [
	{ id: 1, recommendation_id: 0, operator: 'op-smoke', action: 'APPROVED', note: 'seed', decided_at: new Date(Date.now() - 3600_000).toISOString() }
];

const allocations = [
	{ id: 1, recommendation_id: null, idempotency_key: 'seed-000', source_depot_id: 'depot-gazipur', destination_station_id: 'station-tongi', route_id: 'route-gazipur-tongi', fuel_type: 'PETROL', quantity: 3000, created_tick: 10, status: 'ARRIVED', failure_reason: null }
];

const logs = [
	{ ts: new Date().toISOString(), level: 'INFO', component: 'collector', message: 'tick 14 ingested: 12 demand rows, 0 anomalies', data: { tick: 14 } },
	{ ts: new Date().toISOString(), level: 'WARN', component: 'forecaster', message: 'confidence below threshold for station-mirpur/DIESEL — moving average fallback', data: { station_id: 'station-mirpur' } },
	{ ts: new Date().toISOString(), level: 'ERROR', component: 'planner', message: 'LP infeasible for station-coxsbazar/OCTANE — heuristic used', data: { station_id: 'station-coxsbazar' } }
];

// ---- SSE subscribers ----

const sseClients = new Set();
function broadcast(event, data) {
	const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
	for (const res of sseClients) res.write(payload);
}

function findRec(id) { return recommendations.find((r) => r.id === id); }
function json(res, code, body) {
	res.writeHead(code, { 'Content-Type': 'application/json' });
	res.end(JSON.stringify(body));
}

// ---- server ----

const server = createServer((req, res) => {
	const url = new URL(req.url, `http://localhost:${PORT}`);
	const path = url.pathname;

	// SSE stream
	if (path === '/api/stream') {
		res.writeHead(200, {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache',
			Connection: 'keep-alive'
		});
		res.write(': connected\n\n');
		sseClients.add(res);
		req.on('close', () => sseClients.delete(res));
		return;
	}

	// Collect body for POSTs
	if (req.method === 'POST') {
		let body = '';
		req.on('data', (c) => (body += c));
		req.on('end', () => handlePost(req, res, path, body));
		return;
	}

	switch (path) {
		case '/api/state':
			json(res, 200, {
				is_stale: isStale, tick, sim_time: new Date(Date.now()).toISOString(),
				depots, stations, routes, regions, arrivals, events,
				metrics: {
					served_demand_liters: 12345.678, unmet_demand_liters: 234.567,
					service_level: 0.9814, allocation_liters: 9800, allocation_failures: 0
				}
			});
			return;
		case '/api/alerts': json(res, 200, alerts); return;
		case '/api/recommendations': json(res, 200, recommendations); return;
		case '/api/history': json(res, 200, { decisions, allocations }); return;
		case '/api/logs': json(res, 200, logs); return;
		case '/health': {
			const healthy = { component: 'api', status: 'HEALTHY', latency_ms: 12, detail: null, checked_at: new Date().toISOString() };
			json(res, 200, {
				status: isStale ? 'DEGRADED' : 'HEALTHY',
				components: [
					healthy,
					{ component: 'db', status: 'HEALTHY', latency_ms: 3, detail: null, checked_at: new Date().toISOString() },
					{ component: 'simulator', status: isStale ? 'DOWN' : 'HEALTHY', latency_ms: isStale ? null : 45, detail: isStale ? 'connection refused (mock)' : null, checked_at: new Date().toISOString() },
					{ component: 'forecaster', status: 'HEALTHY', latency_ms: 88, detail: null, checked_at: new Date().toISOString() },
					{ component: 'planner', status: 'HEALTHY', latency_ms: 64, detail: null, checked_at: new Date().toISOString() }
				]
			});
			return;
		}
		default:
			json(res, 404, { detail: { code: 'NOT_FOUND', message: `no mock for ${path}` } });
	}
});

function handlePost(req, res, path, raw) {
	let body = {};
	try { body = raw ? JSON.parse(raw) : {}; } catch { /* treated as {} */ }

	let m;
	if ((m = path.match(/^\/api\/recommendations\/(\d+)\/approve$/))) {
		const rec = findRec(Number(m[1]));
		if (!rec) return json(res, 404, { detail: { code: 'NOT_FOUND', message: `recommendation ${m[1]} not found` } });
		if (rec.status !== 'PROPOSED') return json(res, 409, { detail: { code: 'ALREADY_DECIDED', message: `recommendation already ${rec.status}` } });
		rec.status = 'APPROVED';
		// create one allocation per item, PENDING → IN_TRANSIT after 2s → ARRIVED after 6s
		for (const item of rec.items) {
			const alloc = {
				id: nextAllocationId++, recommendation_id: rec.id,
				idempotency_key: `${rec.id}:${item.id}`,
				source_depot_id: item.depot_id, destination_station_id: item.station_id,
				route_id: item.route_id, fuel_type: item.fuel_type, quantity: item.quantity,
				created_tick: tick, status: 'PENDING', failure_reason: null
			};
			allocations.unshift(alloc);
			setTimeout(() => { alloc.status = 'IN_TRANSIT'; broadcast('allocation.status_changed', alloc); }, 2000);
			setTimeout(() => { alloc.status = 'ARRIVED'; broadcast('allocation.status_changed', alloc); }, 6000);
		}
		decisions.unshift({
			id: nextDecisionId++, recommendation_id: rec.id, operator: 'op-smoke',
			action: 'APPROVED', note: '', decided_at: new Date().toISOString()
		});
		broadcast('recommendation.decided', { id: rec.id });
		return json(res, 200, { ok: true });
	}

	if ((m = path.match(/^\/api\/recommendations\/(\d+)\/reject$/))) {
		const rec = findRec(Number(m[1]));
		if (!rec) return json(res, 404, { detail: { code: 'NOT_FOUND', message: `recommendation ${m[1]} not found` } });
		if (rec.status !== 'PROPOSED') return json(res, 409, { detail: { code: 'ALREADY_DECIDED', message: `recommendation already ${rec.status}` } });
		rec.status = 'REJECTED';
		decisions.unshift({
			id: nextDecisionId++, recommendation_id: rec.id, operator: 'op-smoke',
			action: 'REJECTED', note: String(body.note ?? ''), decided_at: new Date().toISOString()
		});
		broadcast('recommendation.decided', { id: rec.id });
		return json(res, 200, { ok: true });
	}

	if ((m = path.match(/^\/api\/alerts\/(\d+)\/ack$/))) {
		const alert = alerts.find((a) => a.id === Number(m[1]));
		if (!alert) return json(res, 404, { detail: { code: 'NOT_FOUND', message: `alert ${m[1]} not found` } });
		alert.status = 'ACKED';
		broadcast('alert.acknowledged', { id: alert.id });
		return json(res, 200, { ok: true });
	}

	// ---- test-only controls (not part of the app contract) ----
	if (path === '/__mock__/stale') {
		isStale = !isStale;
		broadcast('simulator.notice', { message: `stale=${isStale}` });
		return json(res, 200, { is_stale: isStale });
	}
	if (path === '/__mock__/tick') {
		tick += 1;
		stations[0].inventory.DIESEL = Math.max(0, stations[0].inventory.DIESEL - 400);
		broadcast('simulation.tick', { tick, sim_time: new Date().toISOString() });
		return json(res, 200, { tick });
	}
	if (path === '/__mock__/reset') {
		recommendations[0].status = 'PROPOSED';
		alerts[0].status = 'OPEN';
		alerts[1].status = 'OPEN';
		return json(res, 200, { ok: true });
	}

	json(res, 404, { detail: { code: 'NOT_FOUND', message: `no mock for ${path}` } });
}

server.listen(PORT, () => {
	console.log(`mock backend on http://localhost:${PORT} (SSE /api/stream, controls POST /__mock__/{stale,tick,reset})`);
});
