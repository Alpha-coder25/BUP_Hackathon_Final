# Application Flow — System View

How data moves through the system per tick and per decision. Stack and components: `TRD.md`.

## Continuous loop (every tick, driven by SSE `simulation.tick` or 30–60s poll)

```
Simulator /v1/*  ──► Collector ──► validate ──► PostgreSQL (snapshots, demand_observations)
                     │  on failure: retry ×3 backoff → last-good cache + is_stale=true
                     ▼
              Forecaster ──► forecasts (P10/P50/P90) ──► risk_assessments (hours_to_stockout, prob)
                     │           │ model error / thin data → moving-average fallback
                     ▼           ▼
              Anomaly rules ──► alerts (spike / inventory drop / shipment delay)
                     │
                     ▼
              Optimizer (LP over open routes) ──► recommendations + items (PROPOSED)
                     │  optimizer failure / low confidence → heuristic fallback
                     ▼
              GenAI explanation (facts → 3 sentences; template on failure)
```

## Decision write path (operator clicks Approve)

```
POST /api/recommendations/{id}/approve
  → backend: re-check constraints (route open, depot stock, station capacity)
  → POST /v1/allocations per item, idempotency_key = {rec_id}:{seq}
      201 new / 200 replay / 409 → map error to user message (split, wait, reroute)
  → decision row (APPROVED, operator) + allocation rows (PENDING)
  → simulator advances tick: PENDING → IN_TRANSIT → ARRIVED | FAILED
  → allocation.status_changed via SSE → update DB, recompute risk
```

Reject → `decision` row REJECTED, recommendation EXPIRED, alert stays OPEN.

## Crisis recompute path (event ingested)

```
/v1/events shows ACTIVE event
  → apply to model inputs: demand↑ (multiplier) | route removed | depot stock↓ | arrival pushed out
  → re-forecast → re-assess risk → re-run LP → new recommendation "Recovery plan"
  → alert raised with cause; UI shows before/after risk
```

## Failure & recovery path

```
Component health probe (5s) → service_health_checks
  probe fail → fallback_events row → policy switches
     forecaster down → moving average
     planner down   → nearest-depot heuristic
     simulator 503  → cached state + stale banner, writes paused
  probe recovers → auto-resume normal pipeline, fallback ended
```

## Invariants

- REST is source of truth; SSE only triggers re-GET.
- Every write has a unique idempotency key; replays are safe.
- No allocation without an approved recommendation (or explicit manual override, audited).
- Risk recomputed after every allocation status change.
