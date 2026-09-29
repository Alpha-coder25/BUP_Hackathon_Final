# BUP CSE Fest 2026 - Step-by-Step Build Guide

**Fuel Supply Intelligence & Resilience Platform | Skipping Sections 13 and 20**

---

## The Big Picture

```text
Simulator API --> [Phase 1: Collector] --> Database
                                              |
                          [Phase 2: Forecast + Anomaly detection]
                                              |
                          [Phase 3: Optimizer (LP) = hybrid decision]
                                              |
                          [Phase 5: Dashboard + Approve button] --> POST /allocations
```

| Phase | Covers | What you get |
|-------|--------|--------------|
| 1 | Page 2 Environment, Section 4 | Live simulator data flowing into your system |
| 2 | Section 7 Intelligence | Forecast, shortage risk, anomaly alerts, explanations |
| 3 | Section 21 Optimization + ML hybrid | Allocation recommendations with expected impact |
| 4 | Section 8 Reinforcement learning | Optional. Do last, or skip |
| 5 | Required extras (sections 12, 14, 15, 17) | Docker, health page, metrics, load test |

**Suggested stack (simple and fast):** Python + FastAPI (backend), scikit-learn (forecast), PuLP (optimizer), PostgreSQL (data), React or Next.js (dashboard), Docker Compose (run everything).

---

## Phase 0: Project Setup (15 minutes)

1. Create one repo with three folders: `backend/`, `web/`, `mock_simulator/`.
2. Create `.env.example` with `SIM_URL`, `DB_URL`, `LLM_API_KEY`. Never hard-code secrets (section 18).
3. Write a `README.md` with the 3 commands to run the project. Judges read this first.

---

## Phase 1: Connect to the Simulator (Page 2 Environment + Section 4)

**Goal:** get real data in. Do not build your own simulator: the organizers provide the world.

1. Read the simulator docs when released. Note the exact JSON fields for stations, depots, routes, events, and the `POST /allocations` body.
2. Write one small client file. All simulator calls go through it, so a failure is handled in one place.
3. Run a collector loop every 30 to 60 seconds. Save each snapshot to the database with a timestamp.
4. Keep a copy of the last good data. If the simulator is down, the app shows cached data with a warning banner.
5. Write a tiny mock of the endpoints (fixed JSON). Use it when the real simulator is not reachable.

```python
# backend/simulator_client.py
import os, time, requests

BASE = os.getenv("SIM_URL", "http://simulator:8000")
_cache = {}

def fetch(path, retries=3):
    for i in range(retries):
        try:
            r = requests.get(BASE + path, timeout=5)
            r.raise_for_status()
            _cache[path] = r.json()      # remember last good data
            return _cache[path], False   # (data, is_stale)
        except Exception:
            time.sleep(2 ** i)           # wait 1s, 2s, 4s
    return _cache.get(path), True        # fallback to cache, mark stale
```

> **Judge point:** validate every response (check required fields exist and numbers are not negative). Bad data raises a system alert instead of crashing.

---

## Phase 2: Intelligence (Section 7)

Build three small things. Together they meet the requirement and are easy to demo.

### 2A. Demand forecast and shortage risk (Prediction)

1. From `/demand-history`, build a table per station and fuel: time, demand, hour, day of week, last demand, 6-hour average.
2. Train three models: P10, P50, P90 (low, expected, high demand). This gives you uncertainty for free.
3. Compute hours to stockout = (inventory + incoming supply) divided by expected demand per hour.
4. Compute stockout risk % by simulating many demand values (shown in Phase 3 code).
5. Fallback: if the model fails or has too little data, use a simple moving average.

```python
# backend/forecast.py
from sklearn.ensemble import GradientBoostingRegressor
import pandas as pd

def features(df):  # df has columns: ts, demand
    df = df.copy()
    df["hour"] = df.ts.dt.hour
    df["dow"] = df.ts.dt.dayofweek
    df["lag1"] = df.demand.shift(1)
    df["roll6"] = df.demand.rolling(6).mean()
    return df.dropna()

def train(df):
    d = features(df)
    X = d[["hour", "dow", "lag1", "roll6"]]
    return {q: GradientBoostingRegressor(loss="quantile", alpha=q).fit(X, d.demand)
            for q in (0.1, 0.5, 0.9)}

def predict(models, row):
    return {q: float(m.predict(row)[0]) for q, m in models.items()}

def moving_avg(df, n=6):  # FALLBACK when model is unavailable
    return float(df.demand.tail(n).mean())

def low_confidence(p):  # wide gap between P10 and P90 = unsure
    return (p[0.9] - p[0.1]) / max(p[0.5], 1e-6) > 0.8
```

### 2B. Anomaly detection (Detection)

1. For each station, compare the newest demand to its recent average. If it is more than 3 standard deviations away, raise a **demand spike** alert.
2. Also alert when inventory drops much faster than the forecast, or when a shipment in `/supply-arrivals` is later than its planned time (**shipment delay**).
3. Write every alert to an `alerts` table: time, station, type, severity, reason.

```python
def is_spike(history, latest, z=3.0):
    mu, sd = history.mean(), (history.std() or 1.0)
    return abs(latest - mu) / sd > z
```

### 2C. AI explanation (GenAI, small but impressive)

1. When an alert or recommendation is created, collect the facts: station, fuel, inventory, forecast, cause (spike, delay, route down), and chosen action.
2. Send only those facts to an LLM with the prompt: *explain in 3 short sentences why this alert happened and what the operator should do.*
3. Show the explanation on the alert card. If the LLM call fails, show a template sentence instead (fallback).

---

## Phase 3: Optimization + ML Hybrid (Section 21)

**Idea:** ML predicts how much fuel is needed. Optimization decides who gets what. This is the core of your decision support.

1. For each station and fuel, compute `need = P90 demand over the next hours + safety stock - inventory - incoming supply`. If need is 0 or less, no action.
2. Keep only open routes (from `/routes` and `/events`). A blocked route is simply left out.
3. Solve a small LP: send fuel from depots to stations, minimize transport cost, and punish any unmet need very heavily.
4. Constraints: a depot cannot send more than its stock, and a station should receive close to its need.
5. Calculate risk before and after the plan to show impact (example: 72% to 19%).
6. Show the result as a card with an **Approve** button. Approve calls `POST /allocations` and saves it to decision history.

```python
# backend/optimizer.py
import pulp, numpy as np

def allocate(stock, need, cost):
    # stock: {depot: liters}   need: {station: liters}
    # cost: {(depot, station): cost per liter} (only OPEN routes are included)
    m = pulp.LpProblem("alloc", pulp.LpMinimize)
    x = {k: pulp.LpVariable("x_%s_%s" % k, 0) for k in cost}
    u = {s: pulp.LpVariable("u_" + s, 0) for s in need}  # unmet need
    m += pulp.lpSum(cost[k] * x[k] for k in x) + 1000 * pulp.lpSum(u.values())
    for d in stock:
        m += pulp.lpSum(x[k] for k in x if k[0] == d) <= stock[d]
    for s in need:
        m += pulp.lpSum(x[k] for k in x if k[1] == s) + u[s] >= need[s]
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    plan = {k: x[k].value() for k in x if x[k].value() > 1e-6}
    return plan, {s: u[s].value() for s in need}

def stockout_risk(inv, incoming, alloc, mu, sigma, n=2000):
    demand = np.random.normal(mu, sigma, n)  # sigma is about (P90 - P50) / 1.28
    return float((inv + incoming + alloc - demand < 0).mean())
```

### Handling a crisis (Section 10 scenarios)

| Event from `/events` | What your system does |
|----------------------|-----------------------|
| Shipment delay | Lower that depot's incoming supply, re-forecast, re-run optimizer, alert |
| Demand spike | Anomaly alert, use a higher demand estimate for that region, re-run optimizer |
| Depot constraint | Reduce depot stock in the LP, allocations shift to other depots |
| Route unavailable | Remove that route from the LP, alternative depot is chosen |
| Combined crisis | Apply all changes together, show the new plan and the recovery |

**Safe fallback policy:** if the model or optimizer fails, or confidence is low, use a simple rule (send from the nearest depot with stock to the station with the lowest days of cover) and mark the card **Human review requested**.

---

## Phase 4: Reinforcement Learning (Section 8, optional)

**Recommendation: skip RL.** It is optional and you must prove it beats a simple rule. Your LP already gives strong results. Do this only if everything else is finished.

1. Define a small environment: state (inventory, forecast, supply, route open), action (which depot sends how much), reward (minus unmet demand, minus cost, minus stockouts).
2. Train PPO with Stable-Baselines3 for a few thousand steps.
3. Run RL, LP, and the simple rule on the same 10 scenarios. Compare unmet demand, cost, and stockouts in one table.
4. If RL does not win, say so honestly and keep LP as the main policy.

---

## Phase 5: Required Extras (Sections 12, 14, 15, 17, 18)

These are required even though you skip 13 and 20. Keep each one small.

| Need | Easy way to do it |
|------|-------------------|
| Deployment (12) | `docker-compose.yml` with api, web, db, redis. One command: `docker compose up` |
| Health page (15) | `GET /health` returns status of API, database, simulator, prediction, optimizer. Show green/red badges in the UI |
| Metrics (14) | Add `prometheus-fastapi-instrumentator` (1 line). Track latency, error rate, model confidence, fallback count |
| Logs (14) | JSON logs for actions, failures, decisions. Show the last events in a Logs tab |
| Load test (17) | Run Locust or k6 against `/predict` and `/decide`. Report avg, p50, p95, p99, throughput, error rate |
| Security (18) | Secrets in `.env`, validate inputs, do not crash on bad requests, document assumptions |

```yaml
# docker-compose.yml (minimum)
services:
  api: { build: ./backend, ports: ["8080:8080"], env_file: .env, depends_on: [db, redis] }
  web: { build: ./web, ports: ["3000:3000"], depends_on: [api] }
  db: { image: postgres:16, environment: { POSTGRES_PASSWORD: change_me } }
  redis: { image: redis:7 }
```

### Dashboard screens (Section 6)

- **Overview:** inventory by fuel, station and depot status, map or table.
- **Alerts:** shortage alerts with hours to stockout and AI explanation.
- **Recommendations:** allocation, expected impact, confidence, Approve / Reject.
- **History:** past decisions.
- **Health:** service status, latency, error rate.

---

## Demo Script (Section 22)

1. Show normal operations on the dashboard.
2. Demand rises: the system detects the risk and predicts a shortage.
3. Open the recommendation, show the explanation and impact, click Approve.
4. Trigger a crisis event: the plan updates automatically.
5. Stop the prediction service on purpose: the health page turns red, the fallback policy takes over, operations continue.
6. Show the load-test numbers and the metrics page.

---

## Time Plan and Checklist

| Order | Task | Done when |
|-------|------|-----------|
| 1 | Phase 0 + 1 | Real simulator data is visible in your database |
| 2 | Phase 5: docker compose + `/health` | Whole system starts with one command |
| 3 | Phase 2A + 3 (forecast + LP) | One recommendation card with impact shows on screen |
| 4 | Phase 2B (anomaly) + crisis handling | An injected event changes the plan |
| 5 | Fallback and stale-data banner | Killing a service does not stop the app |
| 6 | Metrics + load test | You have a results table |
| 7 | Phase 2C (GenAI explanation) | Alerts carry an explanation |
| 8 | Phase 4 (RL), only if time remains | Comparison table vs LP |

Skipping 13 and 20 costs you only bonus points in DevOps. Working product (20%), intelligence (20%), resilience (10%) and observability (10%) matter more. Send me the real simulator API docs and I will write the exact client, database tables, and full files for you.