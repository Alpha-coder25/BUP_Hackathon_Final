# TRD — Fuel Supply Intelligence & Resilience Platform

Technical design for the platform described in `PRD.md`.

## 1. Architecture

```
Simulator API (docker, :8000)
        │  REST poll (30–60s) + SSE /v1/stream (push hint)
        ▼
[Collector] ──► PostgreSQL (snapshots, demand, alerts, decisions)
        │
        ├── [Forecaster]  sklearn GradientBoosting quantile P10/P50/P90, moving-average fallback
        ├── [Anomaly]     z-score spike / inventory-drop / shipment-delay rules
        └── [Optimizer]   PuLP LP: min transport cost + 1000×unmet, open routes only
        ▼
FastAPI backend (:8080)  ──►  Next.js/React dashboard (:3000)
        │                        Overview · Alerts · Recommendations · History · Health
        └── /health, /metrics (prometheus-fastapi-instrumentator), JSON logs
```

One repo: `backend/`, `web/`, `mock_simulator/`. Redis for queue/cache.

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | async, SSE client, fast to build |
| Forecast | scikit-learn `GradientBoostingRegressor(loss="quantile", alpha)` ×3 | uncertainty bands free |
| Anomaly | stdlib statistics (z-score) | no dependency |
| Optimizer | PuLP + CBC | small LP, exact solve |
| DB | PostgreSQL 16 | time-series snapshots, JSONB |
| Web | Next.js/React | operator dashboard |
| Deploy | Docker Compose (api, web, db, redis) | one-command reproducibility |
| GenAI | LLM API keyed via `.env`, template fallback | explanations, not chatbot |

## 3. Simulator Integration

Single client module `backend/simulator_client.py` — every simulator call routes through it.

- **Read:** `GET /v1/health`, `/v1/instance`, `/v1/depots`, `/v1/stations`, `/v1/routes`, `/v1/supply-arrivals`, `/v1/demand-history?limit=200`, `/v1/events`, `/v1/allocations`, `/v1/metrics`.
- **Write:** `POST /v1/allocations` with body `{idempotency_key, source_depot_id, destination_station_id, route_id, fuel_type, quantity}`; `idempotency_key` = `{recommendation_id}:{item_seq}` so retries are safe. `POST /v1/allocations/{id}/cancel` for PENDING-only rollback.
- **Push:** SSE `/v1/stream` (`simulation.tick`, `allocation.status_changed`, `inventory.updated`, `simulator.notice`). SSE is advisory only — re-GET REST after every event and after every reconnect (no `Last-Event-ID` replay; queue drops silently past 200).
- **Validation:** reject missing fields / negative numbers; raise system alert on bad data instead of crashing.
- **Cache:** keep last good response per path; on failure return cache + `is_stale=true`.

## 4. Data Model

Full ERD in `ERD.md`. Groups:
- **World snapshots:** `depot_inventory_snapshots`, `station_inventory_snapshots`, `demand_observations`, `supply_arrivals`, `sim_events` — append-only per tick.
- **Intelligence:** `model_versions`, `forecasts` (predicted/lower/upper), `risk_assessments` (hours_to_stockout, stockout_probability, severity, confidence), `alerts`.
- **Decision:** `recommendations` + `recommendation_items` (per depot→station×fuel×route), `decisions` (approve/reject audit), `allocations` (mirrors simulator ledger, unique `idempotency_key`).
- **Ops:** `service_health_checks`, `fallback_events`, `benchmark_runs`, `audit_log`, `operators`.

## 5. Core Algorithms

**Forecast (per station×fuel).** Features: hour, day-of-week, lag-1 demand, 6-tick rolling mean. Three quantile models (P10/P50/P90). `hours_to_stockout = (inventory + in-flight + incoming) / P50 per hour`. Risk % = Monte Carlo (2000 draws of N(P50, σ), σ = (P90−P50)/1.28) counting demand > supply. Confidence low when `(P90−P10)/P50 > 0.8` or < 20 history rows → moving-average fallback.

**Anomaly.** Demand spike: `|latest − μ|/σ > 3`. Inventory drop vs forecast; supply arrival `actual_tick > planned_tick` → delay alert. All written to `alerts`.

**Optimizer.** For each station×fuel: `need = P90 demand over horizon + safety stock − inventory − incoming`; skip if ≤ 0. LP over open routes only:

min Σ cost·x + 1000·Σ u  s.t. Σ x[d,*] ≤ stock[d]; x + u ≥ need; 0 ≤ x ≤ route.max_shipment

Output plan → recommendation with `risk_before` / `risk_after` (Monte Carlo), confidence, explanation, alternatives. Submit respects `route.max_shipment`, `dispatch_capacity_per_tick`, `station.capacity`.

**Crisis handling.** On event: apply effect to inputs (lower depot stock, drop disrupted routes, raise regional demand, push out delayed arrivals) → re-forecast → re-optimize → alert.

**Fallback policy.** Optimizer or model unavailable / low confidence → heuristic: nearest depot with stock → station with lowest hours of cover; card marked **"Human review requested"**; logged to `fallback_events`.

## 6. API (our backend)

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Latest snapshot: depots, stations, routes, arrivals, events, metrics |
| `GET /api/alerts` | Alert feed with GenAI explanations |
| `GET /api/recommendations` / `POST /api/recommendations/{id}/approve` / `/reject` | Decision loop |
| `GET /api/history` | Decision + allocation history |
| `GET /health` | api, db, simulator, forecaster, planner status |
| `/metrics` | Prometheus |

## 7. Resilience

- Retries with exponential backoff (1s/2s/4s) in the simulator client; 3 attempts then cache+stale.
- `X-Simulator-Stale: true` → invalidate cache, show banner.
- Prediction service down → moving average; optimizer down → heuristic policy; either → `fallback_events` row + UI badge.
- `/v1/health` used as liveness probe (bypasses faults); all resilience tests hit `/v1/*` (never `/admin/*` to fake success).
- Human review forced when confidence low; decision always auditable in `decisions` + `audit_log`.

## 8. Observability & Testing

- Metrics: request rate/latency/error rate, model confidence, fallback count, forecast MAPE.
- JSON structured logs for actions, integration failures, decisions, recoveries; Logs tab in UI.
- Load test: Locust/k6 on `/predict` and `/decide`; report avg/p50/p95/p99, throughput, error rate, concurrency.
- Tests: unit tests for forecast features, LP constraint satisfaction, idempotency-key generation; one integration test against the mock simulator.
