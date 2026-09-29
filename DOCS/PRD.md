# PRD — Fuel Supply Intelligence & Resilience Platform

**BUP CSE Fest 2026 Hackathon Finals** (with Poridhi.io) · v1.0

## 1. Problem

A simulated Bangladeshi fuel supply network (2 regions, 2 depots, 4 stations, 6 routes, 3 fuels) faces demand spikes, shipment delays, route disruptions, and depot constraints. Operations teams have no tooling to see shortages coming, decide who gets constrained fuel, or stay operational during failures. The organizer-provided **BUP Fuel Supply Simulator** is the world; our product is the brain on top of it.

## 2. Goal

A decision-support platform that lets an operator **Observe → Detect → Predict → Decide → Act → Monitor → Recover** the simulated network, and keeps working when components fail.

## 3. Users

| User | Needs |
|---|---|
| Fuel operations operator | See network state, get shortage alerts, approve/reject allocation recommendations |
| Judge / admin (viewer role) | Inspect decisions, explanations, health, and load-test evidence |

Human approval is preserved for every consequential decision — the system recommends, the operator disposes.

## 4. Functional Requirements

| # | Requirement | Priority |
|---|---|---|
| F1 | Ingest simulator state (depots, stations, routes, supply arrivals, demand history, events) via REST + SSE, every tick | Must |
| F2 | Dashboard: inventory by fuel, depot/station status, regional demand, incoming supply | Must |
| F3 | Demand forecast (P10/P50/P90) per station×fuel + **hours-to-stockout** and **stockout probability** | Must |
| F4 | Anomaly detection: demand spikes (z-score), abnormal inventory drops, shipment delays | Must |
| F5 | Alert feed with severity, cause, and a 3-sentence **GenAI explanation** (template fallback) | Must |
| F6 | Allocation recommendation: LP optimizer (min transport cost, heavy unmet-need penalty) over open routes only, with risk-before/after and confidence | Must |
| F7 | Approve → `POST /v1/allocations` (idempotency-keyed, route.max_shipment respected) + decision history; Reject records the decision | Must |
| F8 | Crisis handling: recompute on `demand_spike`, `route_disruption`, `station_outage`, `depot_constraint`, `shipment_delay`, `supply_shortfall` | Must |
| F9 | Resilience: retry/backoff, last-good cache with stale banner, fallback heuristic policy, `X-Simulator-Stale` handling, health page | Must |
| F10 | Observability: `/health` per component, metrics (latency, error rate, model confidence, fallback count), JSON logs | Must |
| F11 | Optional: RL comparison vs LP, simulation replay | Won't (time permitting) |

## 5. Non-Functional Requirements

- **Deployment:** one command — `docker compose up` (api, web, db, redis).
- **Performance:** decision path p95 < 500 ms under normal load; load-tested with published p50/p95/p99, throughput, error rate.
- **Security:** secrets in `.env`, validated inputs, no simulator-source modification, no real-world writes.
- **Constraints:** operate only against the simulator; REST is source of truth; every `POST /allocations` carries a unique idempotency key.

## 6. Success Metrics

- Working end-to-end approve loop (alert → recommendation → approve → allocation ARRIVED).
- Service level (served / (served + unmet)) ≥ 0.98 in normal runs; measurable improvement after recommendations (e.g., stockout risk 72% → 19%).
- Survives injected failures: simulator fault, prediction service down → fallback activates, health page shows it, operations continue.

## 7. Out of Scope

Own simulator, real fuel infrastructure, enterprise auth, Kubernetes, chatbot around the app.
