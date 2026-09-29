// Types mirroring the backend API contract (TRD §6) and the simulator world shapes
// the backend re-exposes. Backend only — the UI never talks to the simulator directly.

export type FuelType = 'DIESEL' | 'PETROL' | 'OCTANE';
export type DepotStatus = 'OPEN' | 'CONSTRAINED';
export type StationStatus = 'OPEN' | 'OUTAGE';
export type RouteStatus = 'AVAILABLE' | 'DISRUPTED';
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type Policy = 'optimizer' | 'heuristic' | 'fallback';

export interface Region {
	id: string;
	name: string;
	demand_factor: number;
}

export interface Depot {
	id: string;
	name: string;
	region_id: string;
	status: DepotStatus;
	dispatch_capacity_per_tick: number;
	/** per fuel type, liters */
	capacity: Record<FuelType, number>;
	/** per fuel type, liters */
	inventory: Record<FuelType, number>;
}

export interface Station {
	id: string;
	name: string;
	region_id: string;
	status: StationStatus;
	demand_profile: string;
	demand_multiplier: number;
	/** per fuel type, liters */
	capacity: Record<FuelType, number>;
	/** per fuel type, liters */
	inventory: Record<FuelType, number>;
}

export interface Route {
	id: string;
	source_depot_id: string;
	destination_station_id: string;
	transit_ticks: number;
	max_shipment: number;
	status: RouteStatus;
}

export interface SupplyArrival {
	id: string;
	depot_id: string;
	fuel_type: FuelType;
	quantity: number;
	planned_tick: number;
	actual_tick: number | null;
	status: 'SCHEDULED' | 'DELAYED' | 'ARRIVED';
}

export interface SimEvent {
	id: number;
	type:
		| 'demand_spike'
		| 'route_disruption'
		| 'station_outage'
		| 'depot_constraint'
		| 'shipment_delay'
		| 'supply_shortfall';
	start_tick: number;
	end_tick: number;
	status: 'SCHEDULED' | 'ACTIVE' | 'RESOLVED';
	parameters: Record<string, unknown>;
}

export interface SimMetrics {
	served_demand_liters: number;
	unmet_demand_liters: number;
	service_level: number;
	allocation_liters: number;
	allocation_failures: number;
}

// ---- Intelligence ----

export interface Forecast {
	station_id: string;
	fuel_type: string;
	predicted_liters: number;
	lower_bound: number;
	upper_bound: number;
	hours_to_stockout: number;
	stockout_probability: number;
	severity: Severity;
	confidence: number;
}

/** One demand-observation row as surfaced on the Overview demand table */
export interface DemandRow {
	station_id: string;
	fuel_type: string;
	demand_liters: number;
	served_liters: number;
	unmet_liters: number;
}

export interface Alert {
	id: number;
	type: 'shortage' | 'anomaly' | 'disruption' | 'system';
	severity: Severity;
	station_id: string;
	fuel_type: FuelType;
	message: string;
	status: 'OPEN' | 'ACKED' | 'RESOLVED';
	created_tick: number;
	/** GenAI 3-sentence explanation */
	explanation?: string;
}

export interface RecommendationItem {
	id: number;
	depot_id: string;
	station_id: string;
	route_id: string;
	fuel_type: FuelType;
	quantity: number;
}

export interface Recommendation {
	id: number;
	status: 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
	policy: Policy;
	confidence: number;
	risk_before: number;
	risk_after: number;
	explanation: string;
	alternatives: string[];
	items: RecommendationItem[];
}

export interface Allocation {
	id: number;
	recommendation_id: number | null;
	idempotency_key: string;
	source_depot_id: string;
	destination_station_id: string;
	route_id: string;
	fuel_type: FuelType;
	quantity: number;
	status: 'PENDING' | 'IN_TRANSIT' | 'ARRIVED' | 'FAILED' | 'CANCELLED';
	failure_reason: string | null;
	created_tick: number;
}

export interface Decision {
	id: number;
	recommendation_id: number;
	operator: string;
	action: 'APPROVED' | 'REJECTED' | 'MODIFIED' | 'AUTO';
	note: string;
	decided_at: string;
}

// ---- API payloads (TRD §6) ----

export interface SimState {
	is_stale: boolean;
	tick: number;
	sim_time: string;
	depots: Depot[];
	stations: Station[];
	routes: Route[];
	regions: Region[];
	arrivals: SupplyArrival[];
	events: SimEvent[];
	metrics: SimMetrics;
}

export interface HealthReport {
	/** overall = worst component status */
	status: 'HEALTHY' | 'DEGRADED' | 'DOWN';
	components: ComponentHealth[];
}

export interface ComponentHealth {
	component: string;
	status: 'HEALTHY' | 'DEGRADED' | 'DOWN';
	latency_ms: number | null;
	detail: string | null;
	checked_at: string;
}

/** One JSON structured-log event as shown in the Health screen Logs tab */
export interface LogEntry {
	ts: string;
	level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
	component: string;
	message: string;
	data?: Record<string, unknown>;
}

export class ApiError extends Error {
	constructor(
		public status: number,
		public code: string,
		message: string
	) {
		super(message);
	}
}
