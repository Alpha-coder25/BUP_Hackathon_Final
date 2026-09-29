# Backend Implementation — FastAPI Service & Intelligence Pipeline

Python/FastAPI in `backend/`, port 8080. Phases 1–2 and 4–5 of `Implementation.md`. Algorithms: `TRD.md` §5. Schema: `ERD.md`.

## 1. Module layout

```
backend/
  main.py                  # FastAPI app, routers, startup/shutdown
  simulator_client.py      # ONLY module that talks to the simulator
  collector.py             # tick loop: poll → validate → persist
  forecast.py              # quantile GBM + moving-average fallback
  anomaly.py               # spike / inventory-drop / delay rules
  optimizer.py             # PuLP LP over open routes
  explainer.py             # LLM facts → 3 sentences, template fallback
  risk.py                  # Monte Carlo stockout probability
  health.py                # probes, service_health_checks, fallback events
  db.py  models.py         # SQLAlchemy + ERD models
```

## 2. Simulator client (`simulator_client.py`)

Every `/v1/*` call routes through this module — no exceptions.

- **Reads:** `/v1/health`, `/v1/instance`, `/v1/depots`, `/v1/stations`, `/v1/routes`, `/v1/supply-arrivals`, `/v1/demand-history?limit=200`, `/v1/events`, `/v1/allocations`, `/v1/metrics`.
- **Writes:** `POST /v1/allocations` `{idempotency_key, source_depot_id, destination_station_id, route_id, fuel_type, quantity}`; `POST /v1/allocations/{id}/cancel` (PENDING only).
- **Idempotency key:** `{recommendation_id}:{item_seq}` — retries and replays are safe by construction.
- **Resilience:** 3 attempts, exponential backoff (1s/2s/4s); on exhaustion return last-good cache with `is_stale=true`. Honor `X-Simulator-Stale: true` → invalidate cache.
- **SSE:** `/v1/stream` — events are advisory; on every event and every reconnect, re-GET REST (no `Last-Event-ID` replay; queue drops past 200).
- **Validation:** reject missing fields / negative numbers; bad data raises a system alert, never a crash.

## 3. Collector loop (`collector.py`)

Trigger: SSE `simulation.tick` (fallback 30–60s poll).

1. Re-GET the world reads → validate.
2. Append: `depot_inventory_snapshots`, `station_inventory_snapshots`, `demand_observations`, `supply_arrivals`, `sim_events`.
3. Enqueue the intelligence pipeline (Redis queue, worker per stage).
4. Ingest ACTIVE events → crisis recompute path (§7).

## 4. Intelligence pipeline

**Forecast (`forecast.py`).** Features: hour, day-of-week, lag-1 demand, 6-tick rolling mean. Three `GradientBoostingRegressor(loss="quantile")` models (P10/P50/P90) per station×fuel, persisted with a `model_versions` row. Fallback to moving average when < 20 history rows or `(P90−P10)/P50 > 0.8`.

**Risk (`risk.py`).** `hours_to_stockout = (inventory + in-flight + incoming) / P50`; `stockout_probability` via 2000-draw Monte Carlo of N(P50, σ), σ = (P90−P50)/1.28; severity LOW→CRITICAL; confidence down-weighted when bands are wide.

**Anomaly (`anomaly.py`).** Demand spike `|latest − μ|/σ > 3`; inventory drop vs forecast; arrival `actual_tick > planned_tick` → shipment delay. All → `alerts` with severity + cause.

**Optimizer (`optimizer.py`).** Per station×fuel: `need = P90 horizon demand + safety − inventory − incoming`; skip if ≤ 0. LP (PuLP/CBC) over open routes only:

```
min  Σ cost·x + 1000·Σ u
s.t. Σ_d x[d,*] ≤ stock[d];  x + u ≥ need;  0 ≤ x ≤ route.max_shipment
```

Writes `recommendations` (PROPOSED) + `recommendation_items` with `risk_before`/`risk_after`, confidence, alternatives. Never violates `route.max_shipment`, `dispatch_capacity_per_tick`, `station.capacity`.

**Explainer (`explainer.py`).** Structured facts → LLM → exactly 3 sentences on the alert/recommendation; on any LLM failure, deterministic template. Stored as JSONB on the row.

## 5. API surface (`main.py`)

| Endpoint | Behavior |
|---|---|
| `GET /api/state` | Latest snapshot: depots, stations, routes, arrivals, events, metrics, `is_stale` |
| `GET /api/alerts` | Feed with severity, cause, GenAI explanation |
| `GET /api/recommendations` | PROPOSED cards incl. items + risk deltas |
| `POST /api/recommendations/{id}/approve` | Decision path (§6) |
| `POST /api/recommendations/{id}/reject` | `decisions` REJECTED row, recommendation EXPIRED, alert stays OPEN |
| `GET /api/history` | Decisions + allocations, filterable |
| `GET /health` | api, db, simulator, forecaster, planner → HEALTHY/DEGRADED/DOWN + latency |
| `/metrics` | prometheus-fastapi-instrumentator |

## 6. Decision write path (Approve)

1. Load recommendation; re-check constraints fresh: route open, depot stock, station capacity, `expires_tick`.
2. `POST /v1/allocations` per item, idempotency key `{rec_id}:{seq}` → 201 new / 200 replay; 409 → mapped, actionable error (split, wait, reroute).
3. Write `decisions` (APPROVED, operator) + mirror `allocations` rows (PENDING, unique idempotency key) + `audit_log`.
4. SSE `allocation.status_changed` → update allocation, recompute risk.
5. Cancel: `POST /v1/allocations/{id}/cancel`, PENDING only.

**Constraint:** every idempotency key is unique and never reused across retries of a *different* logical request.

## 7. Crisis recompute

On ACTIVE event from `/v1/events`: apply the effect to model inputs (demand multiplier, drop disrupted routes, lower depot stock, push out delayed arrivals) → re-forecast → re-assess risk → re-run LP → new "Recovery plan" recommendation + alert with before/after risk. Six event types: `demand_spike`, `route_disruption`, `station_outage`, `depot_constraint`, `shipment_delay`, `supply_shortfall`.

## 8. Resilience & health (`health.py`)

- Health probes every 5s → `service_health_checks`; probe fail → `fallback_events` row → policy switch; probe recover → auto-resume normal pipeline.
- Forecaster down / thin data → moving average. Optimizer down / low confidence → nearest-depot heuristic (station with lowest hours of cover), recommendation marked **"Human review requested"**.
- Simulator 503 → cached state + stale banner + **writes paused** (no fresh world, no safe write).
- `/v1/health` as liveness probe (bypasses injected faults). Resilience tests hit `/v1/*` only — never `/admin/*`.

## 9. Observability

- Metrics: request rate/latency/error rate, model confidence, fallback count, forecast MAPE.
- JSON structured logs: actions, integration failures, decisions, recoveries (Logs tab feeds from these).
- Load test: Locust/k6 on `/predict` + `/decide`; record avg/p50/p95/p99, throughput, error rate → `benchmark_runs`.

## 10. Tests

- Unit: forecast feature building, LP constraint satisfaction (all fixtures), idempotency-key generation, Monte Carlo bounds.
- Integration: one end-to-end run against `mock_simulator/` (collect → forecast → recommend → approve → allocation).
- Resilience: simulator fault injection → cache + stale + write-pause; forecaster down → moving average.

**Done when:** a recommendation with risk 72% → 19% renders from the API and the approve loop writes ARRIVED allocations.
