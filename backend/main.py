"""FastAPI entrypoint — Phase 0/1 scope.

Endpoints (`DOCS/TRD.md` §6):
- GET /health      → api, db, simulator (+ forecaster/planner marked pending until Phase 2)
- GET /api/state   → latest world state from Postgres (mirror tables)
- /metrics         → Prometheus (prometheus-fastapi-instrumentator)

The collector loop runs in a background thread on startup (COLLECTOR_ENABLED=0
to disable) — Phase 1 done-when: simulator data lands in Postgres.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from .db import get_engine, init_db
from .simulator_client import get_client

log = logging.getLogger(__name__)

_collector_thread: threading.Thread | None = None


def _start_collector() -> None:
    global _collector_thread
    if os.getenv("COLLECTOR_ENABLED", "1") == "0":
        log.info("collector disabled (COLLECTOR_ENABLED=0)")
        return

    def _run() -> None:
        from .collector import run_forever

        run_forever()

    _collector_thread = threading.Thread(target=_run, name="collector", daemon=True)
    _collector_thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _start_collector()
    yield
    # daemon threads die with the process


app = FastAPI(title="Fuel Supply Intelligence & Resilience Platform", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app)  # /metrics


@app.get("/health")
def health() -> dict:
    """Component health: api, db, simulator (guide §4.1 liveness), forecaster/planner pending."""
    components: dict[str, dict] = {"api": {"status": "HEALTHY"}}

    t0 = time.monotonic()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components["db"] = {"status": "HEALTHY", "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        components["db"] = {"status": "DOWN", "detail": str(exc)[:200]}

    t0 = time.monotonic()
    try:
        data, _ = get_client().health()
        sim_ok = data.get("status") == "ok"
        components["simulator"] = {
            "status": "HEALTHY" if sim_ok else "DEGRADED",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": {"simulation": data.get("simulation")},
        }
    except Exception as exc:  # noqa: BLE001
        components["simulator"] = {"status": "DOWN", "detail": str(exc)[:200]}

    # Wired in Phase 2; honest until then.
    components["forecaster"] = {"status": "DEGRADED", "detail": "wired in Phase 2"}
    components["planner"] = {"status": "DEGRADED", "detail": "wired in Phase 2"}
    return {"components": components}


@app.get("/api/state")
def state() -> dict:
    """Latest world state from Postgres (mirror tables) — dashboard feed seed."""
    from sqlalchemy import select

    from .models import Depot, Region, Route, SimEvent, Station, SupplyArrival

    with get_engine().connect() as conn:
        depots = [
            dict(r._mapping) for r in conn.execute(select(Depot.id, Depot.name, Depot.region_id, Depot.status, Depot.dispatch_capacity_per_tick, Depot.capacity))
        ]
        stations = [
            dict(r._mapping) for r in conn.execute(select(Station.id, Station.name, Station.region_id, Station.status, Station.demand_profile, Station.demand_multiplier, Station.capacity))
        ]
        routes = [
            dict(r._mapping) for r in conn.execute(select(Route.id, Route.source_depot_id, Route.destination_station_id, Route.transit_ticks, Route.max_shipment, Route.status))
        ]
        arrivals = [
            dict(r._mapping) for r in conn.execute(select(SupplyArrival.id, SupplyArrival.depot_id, SupplyArrival.fuel_type, SupplyArrival.quantity, SupplyArrival.planned_tick, SupplyArrival.actual_tick, SupplyArrival.status))
        ]
        events = [
            dict(r._mapping) for r in conn.execute(select(SimEvent.id, SimEvent.type, SimEvent.start_tick, SimEvent.end_tick, SimEvent.status, SimEvent.parameters))
        ]
        regions = [dict(r._mapping) for r in conn.execute(select(Region.id, Region.name, Region.demand_factor))]
    return {
        "regions": regions,
        "depots": depots,
        "stations": stations,
        "routes": routes,
        "supply_arrivals": arrivals,
        "events": events,
    }
