# User Flow — Operator

Primary actor: fuel operations operator. Start: dashboard URL.

## Main loop (happy path)

```
Open dashboard
  → Overview loads (inventory, depot/station status, regional demand, incoming supply)
  → System runs continuously in background (collect → forecast → detect)
  → Alert appears: "station-mirpur DIESEL — projected stockout 6.2h, risk 72%"
  → Operator opens alert card
      → sees: forecast bands, hours-to-stockout, risk %, GenAI explanation (3 sentences)
      → linked recommendation: "Allocate 5,000 L DIESEL from depot-gazipur
         via route-gazipur-mirpur — risk 72% → 19%, confidence 0.87"
  → Operator inspects (route, quantity vs max_shipment, alternatives)
  → clicks APPROVE
      → system POSTs /v1/allocations (idempotency-keyed)
      → card shows PENDING → IN_TRANSIT → ARRIVED
      → risk drops, decision saved to history
  (or clicks REJECT → decision recorded with note, alert stays OPEN)
```

## Alternate flows

- **No alert:** operator browses Overview/History freely; recommendations list may be empty.
- **Low confidence / fallback:** recommendation card is marked "Human review requested" (heuristic policy). Operator decides manually.
- **Stale data:** banner "Simulator data stale — showing cached state" while collector retries.
- **Simulator down:** cached data + banner; approve disabled (no fresh world = no safe write).

## Crisis flow (organizer injects event)

```
Event hits (demand_spike / route_disruption / depot_constraint / shipment_delay / …)
  → SSE tick/notification → re-GET REST
  → forecasts + risk recomputed, new alert raised
  → optimizer re-runs with new constraints (disrupted routes dropped, depot stock reduced)
  → updated recommendation card appears ("Recovery plan")
  → operator approves → allocations re-routed
```

## Failure flow (our own component dies)

```
Prediction service down → health page shows red → forecasts fall back to moving average → operator sees "fallback active" badge → ops continue
Optimizer down → heuristic policy → "Human review requested" card
Recovery → health green → normal pipeline resumes automatically
```
