"""Offline stub of the BUP Fuel Supply Simulator — fixed JSON per guide §4–6.

World data: guide §8 (2 regions, 2 depots, 4 stations, 6 routes, 3 fuels).
Behavior: /v1/health + all GET /v1/* endpoints, POST /v1/allocations with the
guide §5 validation order and idempotency rules, SSE /v1/stream with
simulation.tick events, and the §7.10 fault set (unavailable, error_rate,
stale_data, latency, stream_disconnect) via POST /__mock/faults for resilience
testing. Faults live under /__mock/* so the real /admin/* contract is untouched.

Run:  .venv/bin/python -m mock_simulator.server   → :8000
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

TICK_MINUTES = 15
SIMULATION_SPEED = float(os.getenv("SIMULATION_SPEED", "8"))
FUELS = ("DIESEL", "PETROL", "OCTANE")

# ---------------------------------------------------------------------------
# World (guide §8) — inventory drifts down deterministically per tick
# ---------------------------------------------------------------------------

REGIONS = [
    {"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.00},
    {"id": "region-chattogram", "name": "Chattogram Division", "demand_factor": 1.08},
]

DEPOTS = [
    {
        "id": "depot-gazipur", "name": "Gazipur Depot", "region_id": "region-dhaka",
        "status": "OPEN", "dispatch_capacity_per_tick": 12000,
        "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000},
        "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
    },
    {
        "id": "depot-patiya", "name": "Patiya Depot", "region_id": "region-chattogram",
        "status": "OPEN", "dispatch_capacity_per_tick": 11000,
        "capacity": {"DIESEL": 85000, "PETROL": 65000, "OCTANE": 40000},
        "inventory": {"DIESEL": 55000, "PETROL": 42000, "OCTANE": 24000},
    },
]

STATIONS = [
    {
        "id": "station-mirpur", "name": "Mirpur Fuel Station", "region_id": "region-dhaka",
        "status": "OPEN", "demand_profile": "urban_high", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
        "inventory": {"DIESEL": 9000, "PETROL": 9000, "OCTANE": 5000},
    },
    {
        "id": "station-tongi", "name": "Tongi Fuel Station", "region_id": "region-dhaka",
        "status": "OPEN", "demand_profile": "industrial", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 18000, "PETROL": 9000, "OCTANE": 6000},
        "inventory": {"DIESEL": 11000, "PETROL": 6000, "OCTANE": 3500},
    },
    {
        "id": "station-karnaphuli", "name": "Karnaphuli Fuel Station", "region_id": "region-chattogram",
        "status": "OPEN", "demand_profile": "highway", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 14000, "PETROL": 15000, "OCTANE": 9000},
        "inventory": {"DIESEL": 8500, "PETROL": 9500, "OCTANE": 5200},
    },
    {
        "id": "station-coxsbazar", "name": "Cox's Bazar Fuel Station", "region_id": "region-chattogram",
        "status": "OPEN", "demand_profile": "regional", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 12000, "PETROL": 12000, "OCTANE": 7000},
        "inventory": {"DIESEL": 7500, "PETROL": 7500, "OCTANE": 4200},
    },
]

ROUTES = [
    {"id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "transit_ticks": 2, "max_shipment": 7000, "status": "AVAILABLE"},
    {"id": "route-gazipur-tongi", "source_depot_id": "depot-gazipur", "destination_station_id": "station-tongi", "transit_ticks": 2, "max_shipment": 6500, "status": "AVAILABLE"},
    {"id": "route-patiya-karnaphuli", "source_depot_id": "depot-patiya", "destination_station_id": "station-karnaphuli", "transit_ticks": 2, "max_shipment": 7000, "status": "AVAILABLE"},
    {"id": "route-patiya-coxsbazar", "source_depot_id": "depot-patiya", "destination_station_id": "station-coxsbazar", "transit_ticks": 3, "max_shipment": 6000, "status": "AVAILABLE"},
    {"id": "route-gazipur-karnaphuli", "source_depot_id": "depot-gazipur", "destination_station_id": "station-karnaphuli", "transit_ticks": 4, "max_shipment": 5000, "status": "AVAILABLE"},
    {"id": "route-patiya-mirpur", "source_depot_id": "depot-patiya", "destination_station_id": "station-mirpur", "transit_ticks": 4, "max_shipment": 5000, "status": "AVAILABLE"},
]

# 22-arrival pattern condensed to the first burst (guide §8.7) + two resupplies
SUPPLY_ARRIVALS = [
    {"id": "supply-001", "depot_id": "depot-gazipur", "fuel_type": "DIESEL", "quantity": 18000, "planned_tick": 12, "actual_tick": None, "status": "SCHEDULED"},
    {"id": "supply-002", "depot_id": "depot-gazipur", "fuel_type": "PETROL", "quantity": 14000, "planned_tick": 14, "actual_tick": None, "status": "SCHEDULED"},
    {"id": "supply-003", "depot_id": "depot-patiya", "fuel_type": "DIESEL", "quantity": 16000, "planned_tick": 16, "actual_tick": None, "status": "SCHEDULED"},
    {"id": "supply-004", "depot_id": "depot-patiya", "fuel_type": "OCTANE", "quantity": 8000, "planned_tick": 18, "actual_tick": None, "status": "SCHEDULED"},
]

DEMAND_PROFILES = {  # liters per simulated day (guide §8.5)
    "urban_high": {"DIESEL": 8500, "PETROL": 10500, "OCTANE": 5600},
    "industrial": {"DIESEL": 14000, "PETROL": 4500, "OCTANE": 2200},
    "highway": {"DIESEL": 10500, "PETROL": 11000, "OCTANE": 6200},
    "regional": {"DIESEL": 7200, "PETROL": 7600, "OCTANE": 3600},
}

# ---------------------------------------------------------------------------
# Mutable simulation state
# ---------------------------------------------------------------------------

_state = {
    "tick": 0,
    "status": "RUNNING",
    "paused": False,
    "allocations": [],       # simulator ledger objects
    "idempotency": {},       # key → allocation
    "faults": {},            # type → {"until": wall_time, "params": {...}}
    "sim_time": "2026-01-01T00:00:00+00:00",
    "served": 0.0,
    "unmet": 0.0,
    "history": [],          # real per-tick demand observations (guide §4.11)
    "seq": 1,
}
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
_lock = threading.Lock()
_rng = random.Random(12345)  # deterministic seed (guide §2)


def _iso_sim_time(tick: int) -> str:
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (base + timedelta(minutes=TICK_MINUTES * tick)).isoformat().replace("+00:00", "+00:00")


def _fault_active(kind: str) -> bool:
    f = _state["faults"].get(kind)
    return bool(f and time.monotonic() < f["until"])


def _publish(event: str, payload: dict) -> None:
    """Thread-safe publish: endpoints/tick thread hand off to each subscriber's loop
    (guide §6.1: silently drop slow subscribers)."""
    item = (event, payload)
    for loop, q in list(_subscribers):
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except asyncio.QueueFull:
            pass
        except RuntimeError:
            pass  # subscriber loop gone


# ---------------------------------------------------------------------------
# Tick engine
# ---------------------------------------------------------------------------

def _advance_tick() -> None:
    with _lock:
        _state["tick"] += 1
        tick = _state["tick"]
        _state["sim_time"] = _iso_sim_time(tick)
        day_fraction = TICK_MINUTES / (24 * 60)

        # Demand consumes station inventory; unmet when empty.
        spike = _state.get("spike")
        spike_active = bool(spike and spike.get("ticks_left", 0) > 0)
        for s in STATIONS:
            profile = DEMAND_PROFILES[s["demand_profile"]]
            for fuel in FUELS:
                mult = 1.0
                if (
                    spike_active
                    and (not spike["station_id"] or spike["station_id"] == s["id"])
                    and (not spike["fuel"] or spike["fuel"] == fuel)
                ):
                    mult = float(spike["multiplier"])
                want = profile[fuel] * day_fraction * (1 + _rng.uniform(-0.1, 0.1)) * s["demand_multiplier"] * mult
                served = min(want, s["inventory"][fuel])
                s["inventory"][fuel] = round(s["inventory"][fuel] - served, 1)
                _state["served"] += served
                _state["unmet"] += want - served
                # Record the real observation — demand-history must reflect what
                # actually happened (incl. spikes/unmet), not synthetic noise.
                _state["history"].append({
                    "id": 0, "station_id": s["id"], "fuel_type": fuel, "tick": tick,
                    "sim_time": _state["sim_time"],
                    "demand_liters": round(want, 3), "served_liters": round(served, 3),
                    "unmet_liters": round(want - served, 3),
                })
        if spike_active:
            spike["ticks_left"] -= 1  # once per tick, not per station
            if spike["ticks_left"] <= 0:
                _state["spike"] = None
        if len(_state["history"]) > 6000:  # ~500 ticks × 12 rows — bounded memory
            del _state["history"][: len(_state["history"]) - 6000]

        # Supply arrivals land.
        for a in SUPPLY_ARRIVALS:
            if a["status"] == "SCHEDULED" and a["planned_tick"] <= tick:
                depot = next(d for d in DEPOTS if d["id"] == a["depot_id"])
                cap = depot["capacity"][a["fuel_type"]]
                depot["inventory"][a["fuel_type"]] = round(
                    min(cap, depot["inventory"][a["fuel_type"]] + a["quantity"]), 1
                )
                a["status"], a["actual_tick"] = "ARRIVED", tick

        # PENDING → IN_TRANSIT → ARRIVED per transit_ticks.
        for alloc in _state["allocations"]:
            if alloc["status"] == "PENDING" and alloc["created_tick"] < tick:
                alloc["status"], alloc["departure_tick"] = "IN_TRANSIT", tick
                alloc["expected_arrival_tick"] = tick + _route(alloc["route_id"])["transit_ticks"]
            elif alloc["status"] == "IN_TRANSIT" and alloc["expected_arrival_tick"] is not None and tick >= alloc["expected_arrival_tick"]:
                alloc["status"], alloc["actual_arrival_tick"] = "ARRIVED", tick

    _publish("simulation.tick", {"tick": tick, "sim_time": _state["sim_time"]})


def _route(route_id: str) -> dict:
    return next(r for r in ROUTES if r["id"] == route_id)


def _tick_loop() -> None:
    while True:
        if _state["status"] == "RUNNING":
            try:
                _advance_tick()
            except Exception:
                pass
        time.sleep(1.0 / max(SIMULATION_SPEED, 0.1))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="BUP Fuel Supply Simulator (mock)")


@app.get("/v1/health")
def health():
    return {"status": "ok", "database": "ok", "simulation": {"status": _state["status"], "tick": _state["tick"]}}


def _guard() -> None:
    """§7.10 fault injection on non-health /v1/* GETs."""
    if _fault_active("unavailable"):
        raise HTTPException(503, detail={"code": "FAULT_INJECTED", "message": "Simulator API temporarily unavailable."})
    if _fault_active("error_rate") and _rng.random() < _state["faults"]["error_rate"]["params"].get("rate", 0.25):
        raise HTTPException(503, detail={"code": "FAULT_INJECTED", "message": "Injected transient API error."})
    if _fault_active("latency"):
        time.sleep(_state["faults"]["latency"]["params"].get("delay_ms", 500) / 1000)


def _stale_headers() -> dict:
    return {"X-Simulator-Stale": "true"} if _fault_active("stale_data") else {}


@app.get("/v1/instance")
def instance():
    _guard()
    return JSONResponse(
        {"id": 1, "scenario_id": "baseline", "scenario_version": "1.0", "seed": 12345,
         "sim_time": _state["sim_time"], "tick": _state["tick"], "tick_minutes": TICK_MINUTES,
         "status": _state["status"]},
        headers=_stale_headers(),
    )


@app.get("/v1/regions")
def regions():
    _guard()
    return JSONResponse(REGIONS, headers=_stale_headers())


@app.get("/v1/depots")
def depots():
    _guard()
    return JSONResponse(DEPOTS, headers=_stale_headers())


@app.get("/v1/stations")
def stations():
    _guard()
    return JSONResponse(STATIONS, headers=_stale_headers())


@app.get("/v1/routes")
def routes():
    _guard()
    return JSONResponse(ROUTES, headers=_stale_headers())


@app.get("/v1/supply-arrivals")
def supply_arrivals():
    _guard()
    return JSONResponse(SUPPLY_ARRIVALS, headers=_stale_headers())


@app.get("/v1/events")
def events():
    _guard()
    return JSONResponse([], headers=_stale_headers())


@app.get("/v1/allocations")
def allocations():
    _guard()
    return JSONResponse(_state["allocations"], headers=_stale_headers())


@app.get("/v1/metrics")
def metrics():
    _guard()
    total = _state["served"] + _state["unmet"]
    return JSONResponse(
        {"served_demand_liters": round(_state["served"], 3), "unmet_demand_liters": round(_state["unmet"], 3),
         "service_level": round(_state["served"] / total, 6) if total else 1.0,
         "allocation_liters": sum(a["quantity"] for a in _state["allocations"] if a["status"] in ("IN_TRANSIT", "ARRIVED")),
         "allocation_failures": sum(1 for a in _state["allocations"] if a["status"] == "FAILED")},
        headers=_stale_headers(),
    )


@app.get("/v1/demand-history")
def demand_history(station_id: str = "", limit: int = 200):
    _guard()
    limit = max(1, min(limit, 2000))
    rows = [r for r in _state["history"] if not station_id or r["station_id"] == station_id]
    for i, r in enumerate(rows):
        r["id"] = i + 1
    return JSONResponse(rows[-limit:], headers=_stale_headers())


# ---------------------------------------------------------------------------
# POST /v1/allocations — guide §5 validation order (first failure wins)
# ---------------------------------------------------------------------------

@app.post("/v1/allocations")
def create_allocation(body: dict):
    _guard()

    def err(status: int, code: str, message: str):
        raise HTTPException(status, detail={"code": code, "message": message})

    key = body.get("idempotency_key")
    if not key or not isinstance(key, str) or not (1 <= len(key) <= 150):
        err(422, "VALIDATION", "idempotency_key required (1–150 chars)")
    # 1. Idempotency: same key + same body → replay existing allocation (§5.4)
    prior = _state["idempotency"].get(key)
    if prior is not None:
        if prior["_body"] != body:
            err(409, "IDEMPOTENCY_KEY_MISMATCH", "key already used with a different body")
        return JSONResponse({k: v for k, v in prior.items() if k != "_body"}, status_code=201)

    depot = next((d for d in DEPOTS if d["id"] == body.get("source_depot_id")), None)
    station = next((s for s in STATIONS if s["id"] == body.get("destination_station_id")), None)
    route = next((r for r in ROUTES if r["id"] == body.get("route_id")), None)
    fuel, qty = body.get("fuel_type"), body.get("quantity")
    # 2. NOT_FOUND
    if depot is None or station is None or route is None:
        err(404, "NOT_FOUND", "depot/station/route unknown")
    # 3. ROUTE_MISMATCH
    if route["source_depot_id"] != body["source_depot_id"] or route["destination_station_id"] != body["destination_station_id"]:
        err(409, "ROUTE_MISMATCH", "route endpoints do not match request")
    # 4. DEPOT_CLOSED (CONSTRAINED still shippable)
    if depot["status"] not in ("OPEN", "CONSTRAINED"):
        err(409, "DEPOT_CLOSED", "depot not shippable")
    # 5. STATION_CLOSED
    if station["status"] != "OPEN":
        err(409, "STATION_CLOSED", "station in outage")
    # 6. ROUTE_DISRUPTED
    if route["status"] != "AVAILABLE":
        err(409, "ROUTE_DISRUPTED", "route disrupted")
    # 7. ROUTE_CAPACITY_EXCEEDED
    if not isinstance(qty, (int, float)) or qty <= 0:
        err(422, "VALIDATION", "quantity must be > 0")
    if qty > route["max_shipment"]:
        err(409, "ROUTE_CAPACITY_EXCEEDED", f"quantity exceeds max_shipment {route['max_shipment']}")
    # 8. INSUFFICIENT_INVENTORY
    if depot["inventory"][fuel] < qty:
        err(409, "INSUFFICIENT_INVENTORY", "depot lacks fuel")
    # 9. DISPATCH_CAPACITY_EXCEEDED (in-flight + pending this tick)
    in_flight = sum(a["quantity"] for a in _state["allocations"]
                    if a["source_depot_id"] == depot["id"] and a["status"] in ("PENDING", "IN_TRANSIT"))
    if in_flight + qty > depot["dispatch_capacity_per_tick"]:
        err(409, "DISPATCH_CAPACITY_EXCEEDED", "depot dispatch capacity exceeded this tick")
    # 10. DESTINATION_CAPACITY_EXCEEDED
    if station["inventory"][fuel] + qty > station["capacity"][fuel]:
        err(409, "DESTINATION_CAPACITY_EXCEEDED", "station tank would overflow")
    if fuel not in FUELS:
        err(422, "VALIDATION", f"fuel_type must be one of {FUELS}")

    with _lock:
        alloc = {
            "id": _state["seq"], "idempotency_key": key,
            "source_depot_id": body["source_depot_id"], "destination_station_id": body["destination_station_id"],
            "route_id": body["route_id"], "fuel_type": fuel, "quantity": qty,
            "created_tick": _state["tick"], "departure_tick": None,
            "expected_arrival_tick": None, "actual_arrival_tick": None,
            "status": "PENDING", "failure_reason": None,
        }
        _state["seq"] += 1
        alloc["_body"] = dict(body)
        _state["allocations"].append(alloc)
        _state["idempotency"][key] = alloc
        depot["inventory"][fuel] = round(depot["inventory"][fuel] - qty, 1)  # reserve
    _publish("allocation.status_changed", {k: v for k, v in alloc.items() if k != "_body"})
    return JSONResponse({k: v for k, v in alloc.items() if k != "_body"}, status_code=201)


@app.post("/v1/allocations/{allocation_id}/cancel")
def cancel_allocation(allocation_id: int):
    alloc = next((a for a in _state["allocations"] if a["id"] == allocation_id), None)
    if alloc is None:
        raise HTTPException(404, detail={"code": "ALLOCATION_NOT_FOUND", "message": "unknown allocation"})
    if alloc["status"] != "PENDING":
        raise HTTPException(409, detail={"code": "CANNOT_CANCEL", "message": "only PENDING can cancel"})
    depot = next(d for d in DEPOTS if d["id"] == alloc["source_depot_id"])
    depot["inventory"][alloc["fuel_type"]] = round(depot["inventory"][alloc["fuel_type"]] + alloc["quantity"], 1)
    alloc["status"] = "CANCELLED"
    _publish("allocation.status_changed", {k: v for k, v in alloc.items() if k != "_body"})
    return JSONResponse({k: v for k, v in alloc.items() if k != "_body"})


# ---------------------------------------------------------------------------
# SSE /v1/stream (guide §6) + mock-only fault control
# ---------------------------------------------------------------------------

@app.get("/v1/stream")
async def stream():
    if _fault_active("stream_disconnect"):
        raise HTTPException(503, detail={"code": "FAULT_INJECTED", "message": "stream down"})
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append((asyncio.get_running_loop(), q))

    async def gen():
        yield ": connected\n\n"
        try:
            while True:
                try:
                    event, payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: {event}\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers = [(l, qq) for l, qq in _subscribers if qq is not q]

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/__mock/faults")
def inject_fault(body: dict):
    """Mock-only: {"type": "unavailable|error_rate|stale_data|latency|stream_disconnect",
    "duration_seconds": N, "parameters": {...}} — mirrors guide §7.9/7.10."""
    kind = body.get("type")
    if kind not in ("unavailable", "error_rate", "stale_data", "latency", "stream_disconnect"):
        raise HTTPException(422, "unknown fault type")
    _state["faults"][kind] = {
        "until": time.monotonic() + float(body.get("duration_seconds", 60)),
        "params": body.get("parameters", {}),
    }
    return {"status": "injected", "type": kind}@app.post("/__mock/reset")
def reset():
	_state["tick"] = 0
	_state["allocations"].clear()
	_state["idempotency"].clear()
	_state["faults"].clear()
	return {"status": "reset"}


@app.post("/__mock/spike")
def inject_spike(body: dict):
	"""Mock-only: one-tick demand multiplier — fires a real z>3 demand-spike
	anomaly in the backend's detector (TRD F4). Body: {"station_id": str,
	"fuel": str, "multiplier": float (default 12)}; defaults to all
	stations×fuels when unscoped. Deterministic worlds never trip the spike
	rule on their own — demos/tests use this."""
	station_id = body.get("station_id")
	fuel = body.get("fuel")
	mult = float(body.get("multiplier", 12))
	ticks = int(body.get("duration_ticks", 90))
	_state["spike"] = {"station_id": station_id, "fuel": fuel, "multiplier": mult, "ticks_left": ticks}
	return {"status": "scheduled", "spike": _state["spike"]}


def main() -> None:
    threading.Thread(target=_tick_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
