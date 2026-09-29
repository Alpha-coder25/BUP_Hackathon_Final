# Screen Flow — Operator Dashboard

Five screens (Next.js/React). Global top bar: sim tick/clock, stale-data banner, health badge, operator menu.

```
                    ┌────────────┐
                    │  Overview  │◄──────────────┐
                    └─────┬──────┘               │
             alert click  │   tab nav  ┌─────────┴──┐
                          ▼            │   Alerts   │
                    ┌────────────┐     └─────┬──────┘
                    │Recommend.  │◄───────────┘ (from alert card)
                    └─────┬──────┘
              Approve/Reject
                          ▼
                    ┌────────────┐      ┌────────────┐
                    │  History   │      │   Health   │
                    └────────────┘      └────────────┘
```

## 1. Overview (default)
Inventory by fuel (depots/stations), station & depot status chips (OPEN/CONSTRAINED/OUTAGE), regional demand table, incoming supply list, network map or table. Click station → its forecasts + risk.

## 2. Alerts
Alert cards: severity color, station, fuel, hours-to-stockout, risk %, cause (spike/delay/route), GenAI 3-sentence explanation. Ack / link to recommendation. Empty state: "No active alerts."

## 3. Recommendations
Cards per recommendation: depot→station, route, fuel, quantity (vs route.max_shipment), risk_before → risk_after, confidence bar, alternatives, policy tag (optimizer/heuristic/fallback). "Human review requested" badge when confidence low. Buttons: **Approve** / **Reject (+note)**. After approve: inline allocation status tracker (PENDING → IN_TRANSIT → ARRIVED / FAILED).

## 4. History
Past decisions (approve/reject, operator, note), past allocations with statuses and failure reasons. Filter by station/fuel/date.

## 5. Health
Table: Backend API / Database / Fuel Simulator / Prediction Service / Decision Engine → Healthy/Degraded/Down badges, p95 latency, error rate, fallback-active indicators, recent JSON log events (Logs tab).

## Navigation rules

- Alert card → linked recommendation (deep link).
- Approve disabled when: recommendation expired, simulator unreachable, stale data active.
- Stale-data banner appears on every screen while collector is degraded.
- Health reachable in ≤1 click from anywhere (top bar badge).
