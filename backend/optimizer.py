"""Allocation optimizer: LP over open routes + heuristic fallback.

Contract: `DOCS/TRD.md` §5 (Optimizer), `DOCS/BackendImplementation.md` §4,
simulator guide §5 (write constraints) and §8 (world constants).

- need = P90 demand over horizon + safety stock − inventory − incoming; skip if ≤ 0.
- LP (PuLP/CBC) over AVAILABLE routes only:
      min  Σ cost·x + 1000·Σ u
      s.t. Σ x[depot,fuel,*] ≤ depot stock (per depot×fuel)
           Σ x[depot,*] ≤ dispatch_capacity_per_tick × horizon (per depot)
           x + u ≥ need;  0 ≤ x ≤ route.max_shipment
- Output respects route.max_shipment, depot dispatch_capacity_per_tick and
  station capacity — the same checks the simulator runs on POST /v1/allocations,
  so approved plans don't bounce.
- Fallback (optimizer unavailable / low confidence): nearest-depot heuristic —
  ship from the depot with stock to the station with the lowest hours of cover,
  card marked "Human review requested".
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pulp

log = logging.getLogger(__name__)

UNMET_PENALTY = 1000          # per liter of unmet need (TRD §5)
LP_EPS = 1e-6
HORIZON_TICKS = 8             # plan window: 8 ticks × 15 min = 2 simulated hours
TICK_MINUTES = 15
SAFETY_STOCK_TICKS = 2        # extra cover demanded on top of horizon P90
MAX_PLAN_PER_STATION = 4      # cap items per station to keep the plan reviewable
MONTE_CARLO_DRAWS = 2000
Z_P90 = 1.28
LOW_CONFIDENCE = 0.5

NeedKey = tuple[str, str]     # (station_id, fuel_type)
StockKey = tuple[str, str]    # (depot_id, fuel_type)


@dataclass
class PlanItem:
    """One depot→station shipment — becomes a recommendation_item, then an
    allocation with idempotency_key = {recommendation_id}:{seq}."""

    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: str
    quantity: float              # liters, ≤ route.max_shipment
    transport_cost: float


@dataclass
class Recommendation:
    """Maps to `recommendations` in `DOCS/ERD.md`."""

    items: list[PlanItem]
    policy: str                  # "optimizer" | "heuristic"
    risk_before: float
    risk_after: float
    confidence: float
    explanation: dict = field(default_factory=dict)   # filled by explainer.py
    alternatives: list[dict] = field(default_factory=list)
    human_review_requested: bool = False
    unmet_liters: float = 0.0


# ---------------------------------------------------------------------------
# Inputs (assembled by the pipeline from the collector snapshot + forecasts)
# ---------------------------------------------------------------------------

@dataclass
class RouteOption:
    route_id: str
    source_depot_id: str
    destination_station_id: str
    max_shipment: float
    cost_per_liter: float
    transit_ticks: int


@dataclass
class StationNeed:
    destination_station_id: str
    fuel_type: str
    inventory: float             # current station inventory for this fuel
    incoming: float              # in-flight + scheduled arrivals before horizon
    p50_per_tick: float
    p90_per_tick: float
    station_capacity: float      # station capacity for this fuel (hard cap)

    @property
    def key(self) -> NeedKey:
        return (self.destination_station_id, self.fuel_type)


def liters_needed(need: StationNeed, horizon: int = HORIZON_TICKS) -> float:
    """P90 horizon demand + safety stock − inventory − incoming; ≥ 0."""
    horizon_p90 = need.p90_per_tick * horizon
    safety = need.p50_per_tick * SAFETY_STOCK_TICKS
    return max(0.0, horizon_p90 + safety - need.inventory - need.incoming)


# ---------------------------------------------------------------------------
# Risk (mirrors forecast.stockout_probability; kept local to avoid a cycle)
# ---------------------------------------------------------------------------

def stockout_risk(
    inventory: float, incoming: float, allocated: float, p50: float, p90: float,
    horizon: int = HORIZON_TICKS,
) -> float:
    """P(horizon demand > supply) via 2000 Monte Carlo draws.

    Demand is the SUM over `horizon` ticks (CLT approximation):
    N(horizon·p50, √horizon·σ) with σ = (p90−p50)/1.28 per tick. Drawing a
    single tick against total inventory would read ~0 until the tank is
    nearly empty and hide every real shortage.
    """
    sigma_tick = max((p90 - p50) / Z_P90, 1e-6)
    demand = np.random.normal(horizon * p50, math.sqrt(horizon) * sigma_tick, MONTE_CARLO_DRAWS)
    supply = inventory + incoming + allocated
    return float((demand > supply).mean())


# ---------------------------------------------------------------------------
# LP
# ---------------------------------------------------------------------------

def solve_lp(
    depot_fuel_stock: dict[StockKey, float],
    depot_dispatch_capacity: dict[str, float],
    needs: list[StationNeed],
    routes: list[RouteOption],
) -> tuple[dict[tuple[str, NeedKey], float], dict[NeedKey, float]]:
    """Solve min Σ cost·x + 1000·Σ u over open routes.

    Returns (plan, unmet): plan maps (route_id, need_key) → liters;
    unmet maps need_key → shortfall liters.
    """
    m = pulp.LpProblem("fuel_allocation", pulp.LpMinimize)

    need_by_key = {n.key: n for n in needs}
    route_by_id = {r.route_id: r for r in routes}
    # One variable per (open route, reachable need)
    x: dict[tuple[str, NeedKey], pulp.LpVariable] = {
        (r.route_id, n.key): pulp.LpVariable(
            f"x_{r.route_id}_{n.destination_station_id}_{n.fuel_type}".replace("-", "_"), lowBound=0
        )
        for r in routes
        for n in needs
        if r.destination_station_id == n.destination_station_id
    }
    u: dict[NeedKey, pulp.LpVariable] = {
        n.key: pulp.LpVariable(f"u_{n.destination_station_id}_{n.fuel_type}".replace("-", "_"), lowBound=0)
        for n in needs
    }

    cost = {k: route_by_id[k[0]].cost_per_liter for k in x}
    m += pulp.lpSum(cost[k] * v for k, v in x.items()) + UNMET_PENALTY * pulp.lpSum(u.values())

    # Depot stock, per depot×fuel
    for (depot_id, fuel), stock in depot_fuel_stock.items():
        m += (
            pulp.lpSum(
                v
                for k, v in x.items()
                if route_by_id[k[0]].source_depot_id == depot_id and k[1][1] == fuel
            )
            <= stock
        )
    # Depot dispatch capacity over the horizon, per depot (all fuels combined)
    for depot_id, cap in depot_dispatch_capacity.items():
        m += (
            pulp.lpSum(
                v for k, v in x.items() if route_by_id[k[0]].source_depot_id == depot_id
            )
            <= cap * HORIZON_TICKS
        )
    # Station need (soft, penalized) + capacity (hard)
    for n in needs:
        inflow = pulp.lpSum(v for k, v in x.items() if k[1] == n.key)
        m += inflow + u[n.key] >= liters_needed(n)
        m += inflow <= max(0.0, n.station_capacity - n.inventory)
    # Route capacity
    for r in routes:
        m += pulp.lpSum(v for k, v in x.items() if k[0] == r.route_id) <= r.max_shipment

    m.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[m.status] != "Optimal":
        log.warning("optimizer: LP status %s", pulp.LpStatus[m.status])
        return {}, {n.key: liters_needed(n) for n in needs}

    plan = {k: float(v.value()) for k, v in x.items() if v.value() and v.value() > LP_EPS}
    unmet = {k: float(v.value() or 0.0) for k, v in u.items()}
    return plan, unmet


def optimize(
    *,
    depot_fuel_stock: dict[StockKey, float],
    depot_dispatch_capacity: dict[str, float],
    needs: list[StationNeed],
    routes: list[RouteOption],
    risk_before: dict[NeedKey, float],
) -> Recommendation:
    """Build a Recommendation from LP over open routes. Falls back to the
    nearest-depot heuristic when the LP is unavailable or non-optimal."""
    if not needs or all(liters_needed(n) <= 0 for n in needs):
        # Nothing to ship anywhere: clean no-op, not a fallback event.
        return Recommendation(items=[], policy="optimizer", risk_before=_mean(risk_before, needs),
                              risk_after=_mean(risk_before, needs), confidence=1.0)
    try:
        plan, unmet = solve_lp(depot_fuel_stock, depot_dispatch_capacity, needs, routes)
        if not plan:
            return heuristic_plan(depot_fuel_stock, needs, routes, risk_before)
    except Exception as exc:  # noqa: BLE001 — LP failure must degrade, not crash
        log.warning("optimizer: LP failed (%s) — falling back to heuristic", exc)
        return heuristic_plan(depot_fuel_stock, needs, routes, risk_before)

    route_by_id = {r.route_id: r for r in routes}
    need_by_key = {n.key: n for n in needs}
    items = [
        PlanItem(
            source_depot_id=route_by_id[route_id].source_depot_id,
            destination_station_id=need_by_key[key].destination_station_id,
            route_id=route_id,
            fuel_type=need_by_key[key].fuel_type,
            quantity=round(liters, 1),
            transport_cost=round(liters * route_by_id[route_id].cost_per_liter, 2),
        )
        for (route_id, key), liters in plan.items()
    ]
    items.sort(key=lambda i: (i.destination_station_id, -i.quantity))

    allocated_per_need: dict[NeedKey, float] = {}
    for i in items:
        allocated_per_need[(i.destination_station_id, i.fuel_type)] = (
            allocated_per_need.get((i.destination_station_id, i.fuel_type), 0.0) + i.quantity
        )
    risk_after = {
        n.key: stockout_risk(n.inventory, n.incoming, allocated_per_need.get(n.key, 0.0), n.p50_per_tick, n.p90_per_tick)
        for n in needs
    }
    total_unmet = sum(unmet.values())
    total_need = sum(liters_needed(n) for n in needs)
    return Recommendation(
        items=items,
        policy="optimizer",
        risk_before=_mean(risk_before, needs),
        risk_after=_mean(risk_after, needs),
        confidence=round(max(0.0, 1.0 - total_unmet / max(total_need, 1.0)), 3),
        unmet_liters=round(total_unmet, 1),
    )


def _mean(risk: dict[NeedKey, float], needs: list[StationNeed]) -> float:
    values = [risk.get(n.key, 0.0) for n in needs]
    return round(sum(values) / max(len(values), 1), 4)


# ---------------------------------------------------------------------------
# Fallback policy (TRD §7): nearest depot with stock → lowest hours of cover
# ---------------------------------------------------------------------------

def heuristic_plan(
    depot_fuel_stock: dict[StockKey, float],
    needs: list[StationNeed],
    routes: list[RouteOption],
    risk_before: dict[NeedKey, float],
) -> Recommendation:
    """Simple rule when the optimizer is down or unsure. Marked
    'Human review requested' — the operator decides, not the machine."""
    items: list[PlanItem] = []
    remaining = dict(depot_fuel_stock)
    for n in sorted(needs, key=lambda n: n.inventory / max(n.p50_per_tick, 1e-6)):  # lowest cover first
        want = liters_needed(n)
        candidates = [
            r
            for r in routes
            if r.destination_station_id == n.destination_station_id
            and remaining.get((r.source_depot_id, n.fuel_type), 0.0) > LP_EPS
        ]
        candidates.sort(key=lambda r: (r.transit_ticks, r.cost_per_liter))  # nearest first
        for r in candidates[:MAX_PLAN_PER_STATION]:
            if want <= LP_EPS:
                break
            stock_key = (r.source_depot_id, n.fuel_type)
            room = min(r.max_shipment, remaining[stock_key], want)
            if room <= LP_EPS:
                continue
            room = float(math.floor(room))
            items.append(
                PlanItem(
                    source_depot_id=r.source_depot_id,
                    destination_station_id=n.destination_station_id,
                    route_id=r.route_id,
                    fuel_type=n.fuel_type,
                    quantity=room,
                    transport_cost=round(room * r.cost_per_liter, 2),
                )
            )
            remaining[stock_key] -= room
            want -= room

    allocated_per_need: dict[NeedKey, float] = {}
    for i in items:
        allocated_per_need[(i.destination_station_id, i.fuel_type)] = (
            allocated_per_need.get((i.destination_station_id, i.fuel_type), 0.0) + i.quantity
        )
    risk_after = {
        n.key: stockout_risk(n.inventory, n.incoming, allocated_per_need.get(n.key, 0.0), n.p50_per_tick, n.p90_per_tick)
        for n in needs
    }
    return Recommendation(
        items=items,
        policy="heuristic",
        risk_before=_mean(risk_before, needs),
        risk_after=_mean(risk_after, needs),
        confidence=LOW_CONFIDENCE,
        human_review_requested=True,
    )
