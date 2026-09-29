"""Smoke tests for the backend skeletons — no pytest required.

Run:  .venv/bin/python backend/tests/test_skeletons.py
Covers the unit-test targets from DOCS/TRD.md §8: LP constraint satisfaction,
forecast features/fallback, idempotency-key generation, cache + stale behavior.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from optimizer import (  # noqa: E402
    HORIZON_TICKS,
    Recommendation,
    RouteOption,
    StationNeed,
    heuristic_plan,
    liters_needed,
    optimize,
    solve_lp,
    stockout_risk,
)
from forecast import (  # noqa: E402
    forecast_station_fuel,
    hours_to_stockout,
    is_low_confidence,
    make_features,
    moving_average,
    stockout_probability,
)
from simulator_client import (  # noqa: E402
    SimulatorClient,
    SimulatorDataError,
)

PASS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail and not cond else ''}")
    PASS.append(name)
    assert cond, f"{name} {detail}"


# ---------------------------------------------------------------------------
# Fixture: the §8 world in miniature — 2 depots, 2 stations, 3 routes, 1 fuel
# ---------------------------------------------------------------------------

FUEL = "DIESEL"
STOCK = {("depot-a", FUEL): 10000.0, ("depot-b", FUEL): 4000.0}
DISPATCH = {"depot-a": 12000.0, "depot-b": 11000.0}
ROUTES = [
    RouteOption("r-a1", "depot-a", "station-1", max_shipment=7000, cost_per_liter=1.0, transit_ticks=2),
    RouteOption("r-b1", "depot-b", "station-1", max_shipment=5000, cost_per_liter=3.0, transit_ticks=4),
    RouteOption("r-a2", "depot-a", "station-2", max_shipment=6500, cost_per_liter=1.2, transit_ticks=2),
]
NEEDS = [
    StationNeed("station-1", FUEL, inventory=1000, incoming=0, p50_per_tick=200, p90_per_tick=400, station_capacity=15000),
    StationNeed("station-2", FUEL, inventory=500, incoming=0, p50_per_tick=150, p90_per_tick=300, station_capacity=14000),
]


def test_liters_needed() -> None:
    n = NEEDS[0]
    want = 400 * HORIZON_TICKS + 200 * 2 - 1000 - 0  # p90*H + safety - inv - incoming
    check("liters_needed computes P90 horizon + safety − stock", liters_needed(n) == want,
          f"got {liters_needed(n)}, want {want}")
    dry = StationNeed("s", FUEL, inventory=10**9, incoming=0, p50_per_tick=1, p90_per_tick=1, station_capacity=10**9)
    check("liters_needed floors at 0", liters_needed(dry) == 0.0)


def test_lp_respects_constraints() -> None:
    plan, unmet = solve_lp(STOCK, DISPATCH, NEEDS, ROUTES)
    check("LP produced a plan", bool(plan), f"plan={plan}")

    by_depot: dict[str, float] = {}
    by_route: dict[str, float] = {}
    by_need: dict[tuple[str, str], float] = {}
    route_by_id = {r.route_id: r for r in ROUTES}
    for (route_id, key), liters in plan.items():
        r = route_by_id[route_id]
        by_depot[r.source_depot_id] = by_depot.get(r.source_depot_id, 0.0) + liters
        by_route[route_id] = by_route.get(route_id, 0.0) + liters
        by_need[key] = by_need.get(key, 0.0) + liters

    for depot_id, shipped in by_depot.items():
        check(f"LP depot stock respected ({depot_id})", shipped <= STOCK[(depot_id, FUEL)] + 1e-6,
              f"shipped {shipped} > {STOCK[(depot_id, FUEL)]}")
        check(f"LP dispatch capacity respected ({depot_id})",
              shipped <= DISPATCH[depot_id] * HORIZON_TICKS + 1e-6)
    for route_id, liters in by_route.items():
        cap = route_by_id[route_id].max_shipment
        check(f"LP route max_shipment respected ({route_id})", liters <= cap + 1e-6, f"{liters} > {cap}")
    for n in NEEDS:
        shipped = by_need.get(n.key, 0.0)
        check(f"LP meets or nearly meets need {n.key}",
              shipped + 1e-6 >= min(liters_needed(n), n.station_capacity - n.inventory) - 500,
              f"shipped {shipped} vs need {liters_needed(n)}")
    # Cheapest route preferred: depot-a (cost 1.0) should be drained before depot-b (3.0)
    check("LP prefers cheap route", by_depot.get("depot-a", 0) >= by_depot.get("depot-b", 0) - 1e-6,
          f"a={by_depot.get('depot-a')}, b={by_depot.get('depot-b')}")


def test_optimizer_risk_and_fallback() -> None:
    risk_before = {n.key: 0.9 for n in NEEDS}
    rec: Recommendation = optimize(depot_fuel_stock=STOCK, depot_dispatch_capacity=DISPATCH,
                                  needs=NEEDS, routes=ROUTES, risk_before=risk_before)
    check("optimizer policy is 'optimizer'", rec.policy == "optimizer")
    check("optimizer lowers risk", rec.risk_after < rec.risk_before,
          f"{rec.risk_before} -> {rec.risk_after}")
    check("optimizer confidence in [0,1]", 0.0 <= rec.confidence <= 1.0)
    check("no item exceeds its route max_shipment",
          all(i.quantity <= next(r.max_shipment for r in ROUTES if r.route_id == i.route_id) + 0.5
              for i in rec.items))

    # Broken routes (crisis: all disrupted) → heuristic, human review
    empty_routes: list[RouteOption] = []
    rec2 = optimize(depot_fuel_stock=STOCK, depot_dispatch_capacity=DISPATCH,
                    needs=NEEDS, routes=empty_routes, risk_before=risk_before)
    check("no open routes → heuristic policy", rec2.policy == "heuristic")
    check("heuristic card requests human review", rec2.human_review_requested is True)

    rec3 = heuristic_plan(STOCK, NEEDS, ROUTES, risk_before)
    check("heuristic ships from stock", sum(i.quantity for i in rec3.items) > 0)
    check("heuristic respects stock", all(
        sum(i.quantity for i in rec3.items if i.source_depot_id == d) <= STOCK[(d, FUEL)] + 0.5
        for d in ("depot-a", "depot-b")))


def test_risk_monotone_in_allocation() -> None:
    n = NEEDS[0]
    r0 = stockout_risk(n.inventory, n.incoming, 0, n.p50_per_tick, n.p90_per_tick)
    r1 = stockout_risk(n.inventory, n.incoming, 8000, n.p50_per_tick, n.p90_per_tick)
    check("risk falls as allocation rises", r1 < r0, f"{r0} -> {r1}")
    check("risk in [0,1]", 0.0 <= r0 <= 1.0 and 0.0 <= r1 <= 1.0)


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

def _history(rows: int, base: float = 100.0, noise: float = 0.05, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ticks = np.arange(rows)
    demand = base * (1 + noise * rng.standard_normal(rows)) + 10 * np.sin(ticks / 3)
    times = pd.date_range("2026-01-01", periods=rows, freq="15min")
    return pd.DataFrame({"tick": ticks, "sim_time": times, "demand_liters": demand})


def test_forecast_features() -> None:
    d = make_features(_history(40))
    check("features drop warmup rows (roll6 valid from index 5)", len(d) == 35, f"len={len(d)}")
    check("feature columns present", {"hour", "dow", "lag1", "roll6"} <= set(d.columns))


def test_forecast_gbm_and_fallback() -> None:
    hist = _history(60)
    p = forecast_station_fuel(station_id="station-1", fuel_type=FUEL, history=hist,
                              inventory_liters=3000, incoming_liters=1000,
                              target_tick=60, target_sim_time="2026-01-01T15:00:00")
    check("rich history uses quantile GBM", p.model_kind == "quantile_gbm", p.model_kind)
    check("bands ordered P10 ≤ P50 ≤ P90", p.lower_bound <= p.predicted_liters <= p.upper_bound,
          f"{p.lower_bound} {p.predicted_liters} {p.upper_bound}")
    check("severity valid", p.severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
    check("hours_to_stockout positive", p.hours_to_stockout is None or p.hours_to_stockout > 0)

    thin = _history(10)  # < 20 rows → moving average
    p2 = forecast_station_fuel(station_id="s", fuel_type=FUEL, history=thin,
                               inventory_liters=100, incoming_liters=0,
                               target_tick=10, target_sim_time="2026-01-01T02:00:00")
    check("thin history falls back to moving average", p2.model_kind == "moving_average", p2.model_kind)
    check("fallback marked low confidence", p2.confidence <= 0.5)
    check("fallback prediction equals tail mean (±2dp rounding)",
          abs(p2.predicted_liters - moving_average(thin)) < 5e-3)

    p3 = forecast_station_fuel(station_id="s", fuel_type=FUEL, history=hist,
                               inventory_liters=10**9, incoming_liters=0,
                               target_tick=60, target_sim_time="2026-01-01T15:00:00")
    check("huge inventory → LOW severity", p3.severity == "LOW", p3.severity)


def test_risk_helpers() -> None:
    check("hours_to_stockout None on zero demand",
          hours_to_stockout(1000, 0, 0.0) is None)
    h = hours_to_stockout(1000, 0, 100.0, tick_minutes=15)
    check("hours_to_stockout math (1000L ÷ 400L/h = 2.5h)", h is not None and abs(h - 2.5) < 1e-6, f"h={h}")
    prob = stockout_probability(1000, 0, 100.0, 100.0)
    check("flat bands → deterministic-ish low risk", prob < 0.6, f"prob={prob}")
    check("is_low_confidence flags wide bands", is_low_confidence(100, 100, 200) is True)


# ---------------------------------------------------------------------------
# simulator_client — cache / stale / idempotency / validation
# ---------------------------------------------------------------------------

def test_client_cache_and_stale() -> None:
    state = {"depots_calls": 0, "stale": False, "down": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/depots":
            if state["down"]:
                return httpx.Response(503, json={"error": {"code": "FAULT_INJECTED", "message": "x"}})
            headers = {"X-Simulator-Stale": "true"} if state["stale"] else {}
            state["depots_calls"] += 1
            return httpx.Response(200, headers=headers, json=[{
                "id": "depot-gazipur", "status": "OPEN",
                "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
            }])
        return httpx.Response(404, json={"detail": {"code": "NOT_FOUND", "message": "?"}})

    client = SimulatorClient(base_url="http://test", transport=httpx.MockTransport(handler))

    data, stale = client.fetch("/v1/depots", retries=1)
    check("first fetch fresh", stale is False and data[0]["id"] == "depot-gazipur")

    state["down"] = True
    data, stale = client.fetch("/v1/depots", retries=1)
    check("simulator down → cached data marked stale", stale is True and data[0]["id"] == "depot-gazipur")

    state["down"] = False
    state["stale"] = True
    data, stale = client.fetch("/v1/depots", retries=1)
    check("X-Simulator-Stale → data served but marked stale", stale is True)


def test_client_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "d1", "status": "OPEN", "inventory": {"DIESEL": -5}}])

    client = SimulatorClient(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        client.fetch("/v1/depots", retries=1)
        check("negative inventory raises SimulatorDataError", False)
    except SimulatorDataError:
        check("negative inventory raises SimulatorDataError", True)


def test_idempotency_key_shape() -> None:
    client = SimulatorClient(base_url="http://test")
    k = client.make_idempotency_key("rec-42", 3)
    check("idempotency key = {rec_id}:{seq}", k == "rec-42:3", k)
    check("keys differ per item", k != client.make_idempotency_key("rec-42", 4))
    check("keys differ per recommendation", k != client.make_idempotency_key("rec-43", 3))


def test_allocation_payload_validation() -> None:
    client = SimulatorClient(base_url="http://test")
    kwargs = dict(idempotency_key="k", source_depot_id="d", destination_station_id="s",
                  route_id="r", fuel_type="DIESEL", quantity=100.0)
    try:
        client.create_allocation(**{**kwargs, "quantity": -1})
        check("negative quantity rejected client-side", False)
    except ValueError:
        check("negative quantity rejected client-side", True)
    try:
        client.create_allocation(**{**kwargs, "fuel_type": "LPG"})
        check("bad fuel type rejected client-side", False)
    except ValueError:
        check("bad fuel type rejected client-side", True)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    t0 = time.time()
    test_liters_needed()
    test_lp_respects_constraints()
    test_optimizer_risk_and_fallback()
    test_risk_monotone_in_allocation()
    test_forecast_features()
    test_forecast_gbm_and_fallback()
    test_risk_helpers()
    test_client_cache_and_stale()
    test_client_validation()
    test_idempotency_key_shape()
    test_allocation_payload_validation()
    print(f"\n{len(PASS)} checks passed in {time.time() - t0:.1f}s ✅")
