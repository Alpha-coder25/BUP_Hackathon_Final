# Frontend Implementation — Operator Dashboard (SvelteKit)

SvelteKit 2 + Svelte 5 (runes mode) app in `web/`, port 3000. Screens and navigation: `ScreenFlow.md`. Stack: `TRD.md`. API contract: `TRD.md` §6.

## 1. Project layout

```
web/
  src/
    routes/
      +layout.svelte            # top bar + stale banner + health badge (global chrome)
      +layout.ts                # load: /api/state (is_stale) + /health for top-bar badges
      +page.svelte              # Overview (default)
      alerts/+page.svelte
      recommendations/+page.svelte
      history/+page.svelte
      health/+page.svelte
    lib/
      api/
        client.ts               # typed fetch client for /api/* on :8080
        types.ts                # TS types mirroring the backend API (TRD §6)
        sse.ts                  # EventSource with reconnect + backoff + poll fallback
      state/
        sim.svelte.ts           # shared reactive state (class with $state fields)
      format.ts                 # liters, ticks→hours, severity colors
      components/
        InventoryCard.svelte  StatusChip.svelte  DemandTable.svelte
        AlertCard.svelte  RecommendationCard.svelte  AllocationTracker.svelte
        RiskBadge.svelte  ConfidenceBar.svelte  LogViewer.svelte  HealthTable.svelte
        (RiskBadge/ConfidenceBar: if they stay one-liners, inline them as `{#snippet}` instead of files)
  svelte.config.js
  vite.config.ts
```

## 2. Data access

- **One typed API client** (`lib/api/client.ts`) against our backend only — never the simulator. Mirrors `TRD.md` §6:
  `GET /api/state`, `GET /api/alerts`, `GET /api/recommendations`, `POST /api/recommendations/{id}/approve|reject`, `GET /api/history`, `GET /health`.
  Base URL from `PUBLIC_API_BASE` env (`svelte.config` / `.env`), default `http://localhost:8080`.
- **Live refresh:** SSE from the backend (`lib/api/sse.ts`). Every event → re-GET the affected endpoint (same invariant as the collector: events are hints, not data). `EventSource` reconnects on its own; on repeated failure fall back to 30 s polling; full refetch on reconnect.
- **State model (Svelte 5 runes):**
  - Shared state lives in `lib/state/sim.svelte.ts` — a class with `$state` fields (depots, stations, routes, alerts, recommendations, `is_stale`). Exported via module singleton; components import and read it directly. Reactivity is fine-grained — no store libraries, no context needed for 5 screens.
  - API responses are large and only ever reassigned → plain `$state` fields, replaced by assignment on refetch.
  - Derived values (filtered alert lists, overdue recommendations, count of CRITICAL alerts) use `$derived` — never `$effect` + assignment.
  - Initial render: SvelteKit universal `+page.ts` `load` functions fetch first paint data server-side; hydration takes over from the SSE/refresh loop.
- **Stale propagation:** `is_stale` from `/api/state` lives in the shared state class; `+layout.svelte` renders the global banner from it.

## 3. Screens

### Overview (default, `+page.svelte`)
- Inventory by fuel per depot/station (`InventoryCard`), status chips `OPEN/CONSTRAINED/OUTAGE` (`StatusChip`), regional demand table (`DemandTable`), incoming supply list.
- Click a station → drill-in panel: forecast bands P10/P50/P90, hours-to-stockout, risk %.
- Keyed `{#each}` over stations/depots keyed by entity id (never index).

### Alerts (`alerts/+page.svelte`)
- `AlertCard`s: severity color, station, fuel, hours-to-stockout, risk %, cause tag (spike/delay/route), GenAI 3-sentence explanation.
- Ack button (`onclick`, not `on:click`); deep link `<a href="/recommendations#rec-{id}">` to the triggering recommendation.
- Empty state: "No active alerts."

### Recommendations (`recommendations/+page.svelte`)
- `RecommendationCard`: depot→station, route, fuel, quantity vs `route.max_shipment`, `risk_before → risk_after`, confidence bar, alternatives, policy tag (optimizer/heuristic/fallback).
- **"Human review requested"** badge when confidence low or policy is fallback.
- **Approve / Reject (+note).** Approve disabled when expired / stale / simulator unreachable / already in-flight — disable via `$derived` from card props + shared state.
- After approve: inline `AllocationTracker` — PENDING → IN_TRANSIT → ARRIVED / FAILED (SSE `allocation.status_changed` → refetch allocations; the tracker derives from state).

### History (`history/+page.svelte`)
- Decisions (approve/reject, operator, note) + allocations with statuses and failure reasons. Filter by station/fuel/date — filters are `$state`, the filtered list is `$derived`.

### Health (`health/+page.svelte`)
- `HealthTable`: Backend API / Database / Fuel Simulator / Prediction Service / Decision Engine → Healthy/Degraded/Down badges, p95 latency, error rate, fallback-active indicators.
- Logs tab: recent JSON log events (`LogViewer`).

## 4. Interaction rules (`ScreenFlow.md`)

- Approve disabled when: recommendation expired, simulator unreachable, stale data active.
- Approve disabled after click (in-flight) — the idempotency key makes retries safe, but the UI must not double-submit.
- 409/`max_shipment` rejections from approve → inline actionable message (split shipment, wait next tick, reroute) — never a raw error dump.
- Stale-data banner renders on every screen while collector is degraded; Health reachable in ≤1 click (top-bar badge).

## 5. Design tokens

- Severity: LOW gray · MEDIUM amber · HIGH orange · CRITICAL red.
- Risk display: % + hours-to-stockout always paired. Risk deltas shown as `72% → 19%`.
- Policy tags: optimizer (green) · heuristic (amber) · fallback (red).
- Implementation: CSS custom properties on `+layout.svelte` (`--sev-low`, `--sev-medium`, …) — they inherit into every component; component `<style>` blocks stay scoped (no global CSS framework). Dark operator-friendly theme.

## 6. Build order & checks

Maps to Phases 3–4 of `Implementation.md`:

1. Scaffold SvelteKit app (`web/`, adapter-node for docker) + layout/top bar + `/api/state` wiring → Overview renders from live backend.
2. Alerts + Recommendations + wired Approve/Reject → full loop on screen.
3. History + Health + Logs tab.
4. SSE live refresh + stale banner + disabled-approve edge cases.

**Quality gates for every `.svelte` / `.svelte.ts` file:**
- Run the code through the Svelte MCP `svelte-autofixer` tool before commit (it's wired in `.mcp.json`; the `svelte-code-writer` skill drives it).
- `sv check` (svelte-check) clean; runes mode only — no legacy `export let`, `on:click`, `class:`, `$:`.

**Mock backend & smoke test (no backend required):**
- `node web/mock-backend.mjs` — zero-dependency mock of the full API contract (state, alerts, recommendations + approve/reject, history, health, logs, SSE `/api/stream` with `allocation.status_changed` progression PENDING → IN_TRANSIT → ARRIVED). Test-only controls: `POST /__mock__/stale` (toggle stale banner), `/__mock__/tick`, `/__mock__/reset`.
- `node web/smoke-test.mjs` — starts mock + built app, asserts SSR paint on all screens, the approve loop, stale-banner toggling, and double-approve 409. 23 checks.
- **Switching to the real backend:** no app-code changes. `PUBLIC_API_BASE` is runtime env (`$env/dynamic/public`) — point it at the FastAPI on :8080 and the app talks to it. The mock is opt-in tooling only; delete both scripts once the real contract is verified.

**Done when:** approve loop completes on screen (PENDING → ARRIVED), stale banner shows when the simulator is killed, health badges flip live.
