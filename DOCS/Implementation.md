# Implementation Plan

Build order optimized for a hackathon: working pipeline first, polish last. Stack: `TRD.md`. DB schema: `ERD.md`.

## Phase 0 — Setup (0.5h)
1. Repo layout: `backend/`, `web/`, `mock_simulator/`.
2. `.env.example`: `SIM_URL`, `DB_URL`, `LLM_API_KEY`. README with 3 commands.
3. `docker-compose.yml`: api, web, db (postgres:16), redis. Verify `docker compose up` green.

## Phase 1 — Simulator integration (2h)
1. `backend/simulator_client.py`: all `/v1/*` reads, `POST /v1/allocations` (idempotency key), cancel, retries with backoff, last-good cache + `is_stale`, `X-Simulator-Stale` handling.
2. Collector loop: poll on SSE `simulation.tick` (fallback 30s poll) → validate → write snapshots + demand_observations.
3. `mock_simulator/`: fixed-JSON stub of the endpoints for offline dev/tests.

**Done when:** simulator data is in Postgres.

## Phase 2 — Intelligence (3h)
1. **Forecast** (`forecast.py`): features (hour, dow, lag1, roll6) → 3 quantile GBMs (P10/P50/P90) per station×fuel; moving-average fallback when < 20 rows or wide bands. Compute hours_to_stockout, risk via 2000-draw Monte Carlo.
2. **Anomaly** (`anomaly.py`): z>3 demand spike, inventory-drop vs forecast, shipment delay → `alerts`.
3. **Optimizer** (`optimizer.py`): need = P90 horizon + safety − inv − incoming; PuLP LP over open routes (min cost + 1000×unmet, cap at route.max_shipment); risk_before/after; write recommendation + items.
4. **GenAI**: facts → LLM → 3-sentence explanation on alert/recommendation; template fallback.

**Done when:** a recommendation card with risk 72% → 19% renders in the API.

## Phase 3 — Dashboard (2.5h)
Screens per `ScreenFlow.md`: Overview, Alerts, Recommendations (Approve/Reject wired to `POST /v1/allocations` via backend), History. SSE → live refresh.

**Done when:** full approve loop works on screen.

## Phase 4 — Resilience & ops (2h)
1. `/health` (api, db, simulator, forecaster, planner) + UI Health page with badges.
2. Fallback policies + `fallback_events` logging; stale-data banner; "Human review requested" flow.
3. Prometheus metrics (`prometheus-fastapi-instrumentator`), JSON logs + Logs tab.

## Phase 5 — Crisis & demo readiness (1.5h)
1. Crisis handlers for all 6 event types → recompute pipeline (`ApplicationFlow.md`).
2. Load test (Locust/k6) on `/predict` + `/decide`; record avg/p50/p95/p99, throughput, error rate.
3. Optional: RL comparison table vs LP (skip if time is short).
4. Demo rehearsal per `UserFlow.md` crisis + failure flows.

## Dependency order & checkpoints

```
P0 → P1 → P2 → P3 → P4 → P5
      └────┴────► one-command deploy kept green from P0 onward
```

Checkpoint after each phase: `docker compose up` still works end-to-end.

## Deliberate skips (add if time remains)

- RL (optional, only if it beats LP — prove or omit honestly).
- CI/CD pipeline, automated tests beyond the mock-simulator integration test, model versioning UI, replay.
