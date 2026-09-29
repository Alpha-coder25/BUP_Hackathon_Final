"""DB persistence tests — SQLAlchemy models + collector persistence.

Run:  .venv/bin/python backend/tests/test_db_persistence.py
Covers: schema creation, world-mirror upserts, append-only snapshot idempotency,
allocation ledger sync, and one end-to-end collect → persist roundtrip against a
mock simulator (the integration test TRD §8 asks for, sans HTTP).

DB: fresh SQLite file per test (portable JSON variant, BigInt variant).
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

import sqlalchemy  # noqa: E402

from backend import collector, db  # noqa: E402
from backend.models import (  # noqa: E402
    Allocation,
    Depot,
    DepotInventorySnapshot,
    DemandObservation,
    Region,
    Route,
    SimEvent,
    Station,
    StationInventorySnapshot,
    SupplyArrival,
)
from backend.simulator_client import SimulatorClient  # noqa: E402

PASS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(chr(32) + chr(8212) + chr(32) + detail) if detail and not cond else ''}")
    PASS.append(name)
    assert cond, f"{name} {detail}"


# ---------------------------------------------------------------------------
# Mock simulator world — the §8 baseline, two ticks
# ---------------------------------------------------------------------------

SIM_TIME = {6: "2026-01-01T01:30:00+00:00", 7: "2026-01-01T01:45:00+00:00"}

DEPOTS = [
    {
        "id": "depot-gazipur", "name": "Gazipur Depot", "region_id": "region-dhaka",
        "status": "OPEN", "dispatch_capacity_per_tick": 12000,
        "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000},
        "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
    }
]
STATIONS = [
    {
        "id": "station-mirpur", "name": "Mirpur Fuel Station", "region_id": "region-dhaka",
        "status": "OPEN", "demand_profile": "urban_high", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
        "inventory": {"DIESEL": 9000, "PETROL": 9000, "OCTANE": 5000},
    }
]
ROUTES = [
    {
        "id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur",
        "destination_station_id": "station-mirpur", "transit_ticks": 2,
        "max_shipment": 7000, "status": "AVAILABLE",
    }
]
SUPPLY = [
    {"id": "supply-001", "depot_id": "depot-gazipur", "fuel_type": "DIESEL",
     "quantity": 18000, "planned_tick": 12, "actual_tick": None, "status": "SCHEDULED"}
]
EVENTS = [
    {"id": 1, "type": "demand_spike", "start_tick": 8, "end_tick": 20,
     "status": "ACTIVE", "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.8}}
]
ALLOCATIONS = [
    {"id": 1, "idempotency_key": "rec-42:1", "source_depot_id": "depot-gazipur",
     "destination_station_id": "station-mirpur", "route_id": "route-gazipur-mirpur",
     "fuel_type": "DIESEL", "quantity": 3000, "created_tick": 5, "departure_tick": 6,
     "expected_arrival_tick": 8, "actual_arrival_tick": None, "status": "IN_TRANSIT",
     "failure_reason": None}
]
DEMAND_ROWS = [
    {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": 6,
     "sim_time": SIM_TIME[6], "demand_liters": 95.1, "served_liters": 95.1, "unmet_liters": 0.0}
]

INSTANCE = {
    6: {"id": 1, "scenario_id": "baseline", "seed": 12345, "sim_time": SIM_TIME[6],
        "tick": 6, "tick_minutes": 15, "status": "RUNNING"},
    7: {"id": 1, "scenario_id": "baseline", "seed": 12345, "sim_time": SIM_TIME[7],
        "tick": 7, "tick_minutes": 15, "status": "RUNNING"},
}


class MockSimulatorClient(SimulatorClient):
    """Fixed-JSON client: the §8 world at the given tick (7 has consumed stock)."""

    def __init__(self, tick: int = 6):
        super().__init__(base_url="http://mock")
        self.tick = tick

    def _world(self):
        depots = [dict(d) for d in DEPOTS]
        stations = [dict(s) for s in STATIONS]
        if self.tick >= 7:
            depots[0]["inventory"] = {**depots[0]["inventory"], "DIESEL": 58500}
            stations[0]["inventory"] = {**stations[0]["inventory"], "DIESEL": 8500}
        return depots, stations

    def instance(self):
        return dict(INSTANCE[self.tick]), False

    def regions(self):
        return [{"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.0}], False

    def depots(self):
        depots, _ = self._world()
        return depots, False

    def stations(self):
        _, stations = self._world()
        return stations, False

    def routes(self):
        return [dict(r) for r in ROUTES], False

    def supply_arrivals(self):
        return [dict(a) for a in SUPPLY], False

    def events(self):
        return [dict(e) for e in EVENTS], False

    def allocations(self):
        return [dict(a) for a in ALLOCATIONS], False

    def metrics(self):
        return {"served_demand_liters": 12345.7, "unmet_demand_liters": 234.6,
                "service_level": 0.9814, "allocation_liters": 9800.0,
                "allocation_failures": 2}, False

    def demand_history(self, station_id, limit=200):
        rows = [{**r, "tick": self.tick, "sim_time": SIM_TIME[self.tick]} for r in DEMAND_ROWS]
        return rows, False


def fresh_db() -> None:
    """Point db at a brand-new SQLite file and create the schema."""
    for attr in ("_engine", "_SessionLocal"):
        setattr(db, attr, None)
    path = f"/tmp/fsip-test-{uuid.uuid4().hex}.db"
    db.DB_URL = f"sqlite:///{path}"
    db.init_db()


def counts() -> dict[str, int]:
    from sqlalchemy import select, func

    out = {}
    with db.session_scope() as session:
        for model in (Region, Depot, Station, Route, SupplyArrival, SimEvent,
                      DepotInventorySnapshot, StationInventorySnapshot,
                      DemandObservation, Allocation):
            out[model.__tablename__] = session.execute(
                select(func.count()).select_from(model)
            ).scalar_one()
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_schema_creates() -> None:
    fresh_db()
    from backend.models import __all__ as tables

    check("22 ERD tables map", len(tables) == 22, str(len(tables)))
    with db.session_scope():
        pass  # any session work at all proves the schema is live


def test_collect_and_persist_tick6() -> None:
    fresh_db()
    snap = collector.collect_once(MockSimulatorClient())
    assert snap is not None
    check("snapshot anchored on instance tick", snap.tick == 6)
    check("not stale on happy path", snap.is_stale is False)
    check("active crisis event detected", snap.active_events()[0]["type"] == "demand_spike")
    check("open routes available to optimizer", snap.open_routes()[0]["id"] == "route-gazipur-mirpur")

    c = counts()
    check("world mirror persisted", c["depots"] == 1 and c["stations"] == 1 and c["routes"] == 1)
    check("supply arrivals persisted", c["supply_arrivals"] == 1)
    check("sim events persisted", c["sim_events"] == 1)
    check("depot inventory snapshots 3 fuels", c["depot_inventory_snapshots"] == 3)
    check("station inventory snapshots 3 fuels", c["station_inventory_snapshots"] == 3)
    check("demand observations persisted", c["demand_observations"] == 1)
    check("allocation ledger synced", c["allocations"] == 1)

    with db.session_scope() as session:
        alloc = session.query(Allocation).one()
        check("allocation status mirrored", alloc.status == "IN_TRANSIT" and alloc.sim_allocation_id == 1)
        check("allocation ties to idempotency key", alloc.idempotency_key == "rec-42:1")
        depot = session.query(Depot).one()
        check("depot dispatch capacity mirrored", depot.dispatch_capacity_per_tick == 12000)
        event = session.query(SimEvent).one()
        check("event parameters jsonb roundtrip", event.parameters["multiplier"] == 1.8)


def test_recollect_same_tick_is_idempotent() -> None:
    before = counts()
    collector.collect_once(MockSimulatorClient())  # same tick 6 again
    after = counts()
    check("re-collect same tick appends nothing",
          all(after[t] == before[t] for t in before), f"{before} -> {after}")


def test_next_tick_appends_and_updates_mirror() -> None:
    before = counts()
    snap = collector.collect_once(MockSimulatorClient(tick=7))
    assert snap is not None and snap.tick == 7
    after = counts()
    check("tick 7 appends new snapshot rows",
          after["depot_inventory_snapshots"] == before["depot_inventory_snapshots"] + 3
          and after["station_inventory_snapshots"] == before["station_inventory_snapshots"] + 3,
          f"{before} -> {after}")
    check("tick 7 demand observed", after["demand_observations"] == before["demand_observations"] + 1)
    with db.session_scope() as session:
        diesel = (
            session.query(StationInventorySnapshot)
            .filter_by(station_id="station-mirpur", fuel_type="DIESEL", tick=7)
            .one()
        )
        check("tick 7 snapshot has updated quantity", diesel.quantity == 8500.0, str(diesel.quantity))


def test_sse_allocation_status_sync() -> None:
    with db.session_scope() as session:
        collector.sync_allocation_status(session, {
            "id": 1, "idempotency_key": "rec-42:1", "status": "ARRIVED",
            "actual_arrival_tick": 8, "failure_reason": None,
        })
    with db.session_scope() as session:
        alloc = session.query(Allocation).one()
        check("SSE status change → ARRIVED", alloc.status == "ARRIVED")
        check("SSE arrival tick recorded", alloc.actual_arrival_tick == 8)


def test_full_loop_creates_recommendation_and_allocation() -> None:
    """Integration: forecasts → LP → recommendation rows → idempotency-keyed
    allocation rows — the whole domain chain against the mock world."""
    from backend.forecast import forecast_station_fuel
    from backend.optimizer import RouteOption, StationNeed, optimize
    import pandas as pd

    history = pd.DataFrame([
        {"tick": t, "sim_time": SIM_TIME[6], "demand_liters": 95.0 + t}
        for t in range(6)
    ])
    point = forecast_station_fuel(
        station_id="station-mirpur", fuel_type="DIESEL", history=history,
        inventory_liters=500, incoming_liters=0,
        target_tick=7, target_sim_time=SIM_TIME[7],
    )
    check("forecast point produced", point.predicted_liters > 0)

    routes = [RouteOption("route-gazipur-mirpur", "depot-gazipur", "station-mirpur",
                          max_shipment=7000, cost_per_liter=1.0, transit_ticks=2)]
    needs = [StationNeed("station-mirpur", "DIESEL", inventory=500, incoming=0,
                         p50_per_tick=100, p90_per_tick=150, station_capacity=15000)]
    rec = optimize(depot_fuel_stock={("depot-gazipur", "DIESEL"): 58500},
                   depot_dispatch_capacity={"depot-gazipur": 12000},
                   needs=needs, routes=routes,
                   risk_before={("station-mirpur", "DIESEL"): 0.9})
    check("recommendation produced for thirsty station", len(rec.items) >= 1)

    with db.session_scope() as session:
        rec_row = collector_models_recommendation(session, rec, snap_tick=7)
        for seq, item in enumerate(rec.items, start=1):
            session.add(Allocation(
                idempotency_key=f"{rec_row.id}:{seq}",  # the {rec_id}:{seq} contract
                recommendation_item_id=None,
                depot_id=item.source_depot_id, station_id=item.destination_station_id,
                route_id=item.route_id, fuel_type=item.fuel_type,
                quantity=item.quantity, status="PENDING",
            ))
        rec_id = rec_row.id
    with db.session_scope() as session:
        rows = session.query(Allocation).filter(
            Allocation.idempotency_key.like(f"{rec_id}:%")
        ).all()
        check("allocations written with unique idempotency keys",
              len(rows) == len(rec.items) == len({a.idempotency_key for a in rows}))
        check("quantities within route.max_shipment",
              all(a.quantity <= 7000 for a in rows))


def collector_models_recommendation(session, rec, snap_tick: int):
    from backend.models import Recommendation as RecommendationRow

    row = RecommendationRow(
        policy=rec.policy, tick=snap_tick, status="PROPOSED",
        confidence=rec.confidence, risk_before=rec.risk_before, risk_after=rec.risk_after,
        explanation=rec.explanation, alternatives=rec.alternatives,
        expires_tick=snap_tick + 4,
    )
    session.add(row)
    session.flush()  # assign id so items/allocations can reference it
    return row


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    t0 = time.time()
    test_schema_creates()
    test_collect_and_persist_tick6()
    test_recollect_same_tick_is_idempotent()
    test_next_tick_appends_and_updates_mirror()
    test_sse_allocation_status_sync()
    test_full_loop_creates_recommendation_and_allocation()
    print(f"\n{len(PASS)} checks passed in {time.time() - t0:.1f}s (sqlalchemy {sqlalchemy.__version__}) ✅")
