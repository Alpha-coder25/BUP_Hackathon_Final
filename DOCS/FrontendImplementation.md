# Frontend Implementation — Operator Dashboard

Next.js/React app in `web/`, port 3000. Screens and navigation: `ScreenFlow.md`. Stack: `TRD.md`.

## 1. Project layout

```
web/
  app/
    (dashboard)/
      page.tsx              # Overview (default)
      alerts/page.tsx
      recommendations/page.tsx
      history/page.tsx
      health/page.tsx
    layout.tsx              # top bar + stale banner + health badge
  components/
    InventoryCard.tsx  StationStatusChip.tsx  DemandTable.tsx
    AlertCard.tsx  RecommendationCard.tsx  AllocationTracker.tsx
    RiskBadge.tsx  ConfidenceBar.tsx  LogViewer.tsx  HealthTable.tsx
  lib/
    api.ts                  # typed client for /api/* on :8080
    sse.ts                  # EventSource with reconnect + poll fallback
    format.ts               # liters, ticks→hours, severity colors
  hooks/
    useSimState.ts  useAlerts.ts  useRecommendations.ts  useHealth.ts
```

## 2. Data access

- **One typed API client** (`lib/api.ts`) against our backend only — never the simulator. Mirrors `TRD.md` §6:
  `GET /api/state`, `GET /api/alerts`, `GET /api/recommendations`, `POST /api/recommendations/{id}/approve|reject`, `GET /api/history`, `GET /health`.
- **Live refresh:** SSE from backend (`lib/sse.ts`). Every event → re-GET the affected endpoint (same invariant as the collector: events are hints, not data). Reconnect loop with backoff; on disconnect fall back to 30s polling; full refetch on reconnect.
- **State:** server components for initial render + small client stores per screen (React Query or plain `useSyncExternalStore`). No global state framework needed for 5 screens.
- **Stale propagation:** `is_stale` on `/api/state` drives a global banner in `layout.tsx`.

## 3. Screens

### Overview (default)
- Inventory by fuel per depot/station (cards), status chips `OPEN/CONSTRAINED/OUTAGE`, regional demand table, incoming supply list, network map or table.
- Click a station → drill-in panel: forecast bands (P10/P50/P90), hours-to-stockout, risk %.

### Alerts
- Cards: severity color, station, fuel, hours-to-stockout, risk %, cause tag (spike/delay/route), GenAI 3-sentence explanation.
- Ack button; deep link to the triggering recommendation. Empty state: "No active alerts."

### Recommendations
- Card: depot→station, route, fuel, quantity vs `route.max_shipment`, `risk_before → risk_after`, confidence bar, alternatives, policy tag (optimizer/heuristic/fallback).
- **"Human review requested"** badge when confidence low or policy is fallback.
- **Approve / Reject (+note).** After approve: inline `AllocationTracker` — PENDING → IN_TRANSIT → ARRIVED / FAILED (status via SSE `allocation.status_changed` → refetch).

### History
- Decisions (approve/reject, operator, note) + allocations with statuses and failure reasons. Filter: station, fuel, date.

### Health
- Table: Backend API / Database / Fuel Simulator / Prediction Service / Decision Engine → Healthy/Degraded/Down badges, p95 latency, error rate, fallback-active indicators.
- Logs tab: recent JSON log events.

## 4. Interaction rules (`ScreenFlow.md`)

- Approve disabled when: recommendation expired, simulator unreachable, stale data active.
- Approve disabled after click (in-flight) — the idempotency key makes retries safe, but the UI must not double-submit.
- 409/`max_shipment` rejections from approve → inline actionable message (split shipment, wait next tick, reroute) — never a raw error dump.
- Stale-data banner renders on every screen while collector is degraded; Health reachable in ≤1 click (top-bar badge).

## 5. Design tokens

- Severity: LOW gray · MEDIUM amber · HIGH orange · CRITICAL red.
- Risk display: % + hours-to-stockout always paired. Risk deltas shown as `72% → 19%`.
- Policy tags: optimizer (green) · heuristic (amber) · fallback (red).

## 6. Build order & checks

Maps to Phases 3–4 of `Implementation.md`:

1. Layout + top bar + `/api/state` wiring → Overview renders from live backend.
2. Alerts + Recommendations + wired Approve/Reject → full loop on screen.
3. History + Health + Logs tab.
4. SSE live refresh + stale banner + disabled-approve edge cases.

**Done when:** approve loop completes on screen (PENDING → ARRIVED), stale banner shows when the simulator is killed, health badges flip live.
