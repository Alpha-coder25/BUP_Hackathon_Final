# System Architecture — Fuel Supply Intelligence & Resilience Platform

How the platform is structured. Stack decisions: `TRD.md`. Data model: `ERD.md`. Build order: `Implementation.md`.

## 1. Topology

```
                         ┌──────────────────────────────────────────────┐
                         │            BUP Fuel Supply Simulator          │
                         │              REST /v1/*  +  SSE /v1/stream    │
                         └──────────────┬───────────────────────────────┘
                                        │ REST poll (30–60s) + SSE push hints
                                        ▼
┌──────────────┐   ┌───────────────────────────┐
│    Redis     │◄──┤        Collector          │  validate → retry ×3 backoff
│ queue/cache  │   └──────────────┬────────────┘  on failure: last-good cache + is_stale
└──────┬───────┘                  ▼
       │                ┌──────────────────┐
       │                │   PostgreSQL 16  │  append-only snapshots, forecasts,
       │                │     (:5432)      │  alerts, decisions, allocations
       │                └────────┬─────────┘
       │                         ▼
       │        ┌─────────────────────────────────────┐
       ├───────►│          Intelligence layer          │
       │        │  Forecaster (sklearn quantile GBM)   │
       │        │  Anomaly rules (z-score / drops)     │
       │        │  Optimizer (PuLP LP + CBC)           │
       │        │  GenAI explainer (LLM + template)    │
       │        └────────────────┬────────────────────┘
       │                         ▼
       │        ┌───────────────────────────────┐
       └───────►│       FastAPI backend (:8080) │  /api/*, /health, /metrics, JSON logs
                └──────────────┬────────────────┘
                               │ REST + SSE
                               ▼
                ┌───────────────────────────────┐
                │    Next.js dashboard (:3000)  │  Overview · Alerts ·
                │                               │  Recommendations · History · Health
                └───────────────────────────────┘
```

## 2. Components

| Component | Tech | Responsibility | Port |
|---|---|---|---|
| Simulator | organizer-provided | World simulation; REST source of truth; SSE event hints | 8000 |
| Collector | Python worker | Poll `/v1/*`, validate, persist snapshots + demand; trigger pipeline on tick | — |
| Forecaster | scikit-learn quantile GBM ×3 | P10/P50/P90 per station×fuel; hours-to-stockout; Monte Carlo risk | — |
| Anomaly | stdlib statistics | Spike / inventory-drop / shipment-delay rules → alerts | — |
| Optimizer | PuLP + CBC | LP over open routes: min cost + 1000×unmet → recommendations | — |
| GenAI explainer | LLM API (`.env` key) | Facts → 3-sentence explanations; template fallback | — |
| Backend API | FastAPI | State, alerts, decision loop, history, health, metrics | 8080 |
| Database | PostgreSQL 16 | Time-series snapshots, JSONB intelligence + decision rows | 5432 |
| Cache/queue | Redis | Tick queue, last-good cache hot path | 6379 |
| Dashboard | Next.js/React | Operator UI, SSE live refresh | 3000 |
| Mock simulator | FastAPI stub | Fixed-JSON endpoints for offline dev/tests | 8000 (dev) |

## 3. Data flow (per tick)

Continuous loop and decision write path: `ApplicationFlow.md` (canonical). Summary:

1. **Ingest** — Collector re-GETs REST on SSE `simulation.tick` (advisory only), validates, appends to snapshots/demand tables.
2. **Intelligence** — Forecaster → risk assessment → anomaly rules → optimizer → GenAI explanation.
3. **Expose** — Backend API serves state + recommendations; SSE pushes refresh hints to the dashboard.
4. **Decide** — Operator approves → backend re-checks constraints → idempotency-keyed `POST /v1/allocations` per item → status tracked PENDING → IN_TRANSIT → ARRIVED/FAILED.
5. **Monitor** — Risk recomputed on every allocation status change; health probes every 5s.

## 4. Boundaries & invariants

- **REST is source of truth.** SSE events never carry data worth acting on — they trigger re-GET.
- **Every simulator write** goes through `backend/simulator_client.py` with a unique idempotency key (`{recommendation_id}:{item_seq}`).
- **No allocation without an approved recommendation** (or explicit, audited manual override).
- **Single direction of truth:** simulator → Postgres → API → UI. The UI never talks to the simulator directly.
- **Fail toward the operator, not away from them:** degraded components surface as stale banners, fallback badges, "Human review requested" cards.

## 5. Failure domains

| Failure | Detection | Response |
|---|---|---|
| Simulator read fails / 503 | Client retry ×3 (1s/2s/4s) | Serve last-good cache, `is_stale=true`, stale banner, writes paused |
| `X-Simulator-Stale: true` | Response header | Invalidate cache, banner on all screens |
| Forecaster down / thin data | Health probe / <20 rows or wide bands | Moving-average fallback + `fallback_events` row |
| Optimizer down / low confidence | Health probe / `(P90−P10)/P50 > 0.8` | Nearest-depot heuristic, "Human review requested" card |
| DB down | `/health` probe | API degraded status; reads fail fast, no partial writes |
| SSE connection lost | Reconnect loop | Poll fallback (30s); full re-GET after reconnect (no `Last-Event-ID` replay) |

## 6. Deployment

Single repo, one command:

```
backend/           FastAPI + collector + intelligence modules
web/               Next.js dashboard
mock_simulator/    offline stub of /v1/*
docker-compose.yml api · web · db (postgres:16) · redis
```

`docker compose up` — green from Phase 0 onward, kept green through every phase checkpoint (`Implementation.md`).

## 7. Observability plane

- `/health`: api, db, simulator, forecaster, planner → HEALTHY/DEGRADED/DOWN, surfaced on the Health screen.
- `/metrics`: Prometheus (request rate/latency/errors, model confidence, fallback count, forecast MAPE).
- JSON structured logs: actions, integration failures, decisions, recoveries → Logs tab.
