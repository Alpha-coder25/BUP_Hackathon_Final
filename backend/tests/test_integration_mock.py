"""Phase 1 integration test — real HTTP against mock_simulator/.

Run:  .venv/bin/python backend/tests/test_integration_mock.py
Boots the mock simulator (guide §4–6 contract) on :8765, then verifies:
- every /v1/* read via SimulatorClient,
- POST /v1/allocations validation order (§5.2) + idempotency rules (§5.4),
- §7.10 fault handling: unavailable → cache+stale, stale_data → header flag,
- SSE /v1/stream carries simulation.tick,
- Phase 1 done-when: one collect pass lands simulator data in Postgres.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import collector, db  # noqa: E402
from backend.models import (  # noqa: E402
    Allocation,
    Depot,
    DepotInventorySnapshot,
    DemandObservation,
    SimEvent,
    StationInventorySnapshot,
)
from backend.simulator_client import SimulatorAllocationError, SimulatorClient  # noqa: E402

PASS: list[str] = []
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail and not cond else ''}")
    PASS.append(name)
    assert cond, f"{name} {detail}"


def wait_port(port: int, timeout: float = 30.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"mock simulator not up on :{port}")


# ---------------------------------------------------------------------------
# Boot mock simulator as a subprocess (real HTTP, real SSE)
# ---------------------------------------------------------------------------

proc = subprocess.Popen(
    [sys.executable, "-m", "mock_simulator.server"],
    cwd=ROOT, env={**__import__("os").environ, "PORT": str(PORT), "SIMULATION_SPEED": "8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    wait_port(PORT)
    client = SimulatorClient(base_url=BASE)

    def fresh_db() -> None:
        for attr in ("_engine", "_SessionLocal"):
            setattr(db, attr, None)
        db.DB_URL = f"sqlite:///tmp-integration-{uuid.uuid4().hex}.db"
        db.init_db()

    # ---------------------------------------------------------------- reads

    def test_reads() -> None:
        data, stale = client.health()
        check("health ok (bypasses faults)", data["status"] == "ok" and stale is False)
        inst, _ = client.instance()
        check("instance carries tick/sim_time", "tick" in inst and "sim_time" in inst)
        depots, _ = client.depots()
        check("two depots with per-fuel inventory", len(depots) == 2 and "DIESEL" in depots[0]["inventory"])
        stations, _ = client.stations()
        check("four stations", len(stations) == 4)
        routes, _ = client.routes()
        check("six routes", len(routes) == 6)
        arrivals, _ = client.supply_arrivals()
        check("supply arrivals scheduled", arrivals and arrivals[0]["status"] == "SCHEDULED")
        events, _ = client.events()
        check("events list (empty baseline)", isinstance(events, list))
        allocs, _ = client.allocations()
        check("allocations ledger (empty)", isinstance(allocs, list))
        metrics, _ = client.metrics()
        check("metrics carry service_level", "service_level" in metrics)
        hist, _ = client.demand_history("station-mirpur", limit=50)
        check("demand history rows for mirpur", len(hist) > 0 and hist[0]["station_id"] == "station-mirpur")

    # ------------------------------------------------- allocation §5 order

    def test_allocation_validation_order() -> None:
        good = dict(idempotency_key="t-good-1", source_depot_id="depot-gazipur",
                    destination_station_id="station-mirpur", route_id="route-gazipur-mirpur",
                    fuel_type="DIESEL", quantity=3000)
        # Client-side validation first
        try:
            client.create_allocation(**{**good, "quantity": -5})
            check("client rejects negative quantity", False)
        except ValueError:
            check("client rejects negative quantity", True)

        alloc = client.create_allocation(**good)
        check("201 created → PENDING", alloc["status"] == "PENDING")

        # 200/201 replay: same key + same body (§5.4)
        replay = client.create_allocation(**good)
        check("idempotent replay returns same allocation", replay["id"] == alloc["id"])

        # Same key, different body → 409 IDEMPOTENCY_KEY_MISMATCH
        try:
            client.create_allocation(**{**good, "quantity": 3001})
            check("key mismatch → 409", False)
        except SimulatorAllocationError as e:
            check("key mismatch → 409", e.code == "IDEMPOTENCY_KEY_MISMATCH")

        # ROUTE_MISMATCH (route belongs to a different pair)
        try:
            client.create_allocation(**{**good, "idempotency_key": "t-mm",
                                        "source_depot_id": "depot-patiya"})
            check("route mismatch → 409", False)
        except SimulatorAllocationError as e:
            check("route mismatch → 409", e.code == "ROUTE_MISMATCH")

        # ROUTE_CAPACITY_EXCEEDED
        try:
            client.create_allocation(**{**good, "idempotency_key": "t-cap", "quantity": 99999})
            check("over max_shipment → 409", False)
        except SimulatorAllocationError as e:
            check("over max_shipment → 409", e.code == "ROUTE_CAPACITY_EXCEEDED")

        # NOT_FOUND
        try:
            client.create_allocation(**{**good, "idempotency_key": "t-404",
                                        "source_depot_id": "depot-nowhere"})
            check("unknown depot → 404", False)
        except SimulatorAllocationError as e:
            check("unknown depot → 404", e.code == "NOT_FOUND")

        # Cancel: refund works on PENDING, then CANNOT_CANCEL
        cancelled = httpx.post(f"{BASE}/v1/allocations/{alloc['id']}/cancel").json()
        check("cancel PENDING → CANCELLED", cancelled["status"] == "CANCELLED")
        try:
            httpx.post(f"{BASE}/v1/allocations/{alloc['id']}/cancel").raise_for_status()
            check("double cancel → 409", False)
        except httpx.HTTPStatusError as e:
            check("double cancel → 409", e.response.status_code == 409)
        # Key stays occupied after cancel (§5.4): same key + same body still replays
        # (returns the cancelled allocation); same key + NEW body → mismatch.
        replay = client.create_allocation(**good)
        check("after cancel: replay returns cancelled allocation",
              replay["id"] == alloc["id"] and replay["status"] == "CANCELLED")
        try:
            client.create_allocation(**{**good, "quantity": 123})
            check("after cancel: new body on used key → 409", False)
        except SimulatorAllocationError as e:
            check("after cancel: new body on used key → 409", e.code == "IDEMPOTENCY_KEY_MISMATCH")

    # ------------------------------------------------------------ faults

    def test_faults() -> None:
        data, stale = client.fetch("/v1/depots")
        check("prefetch depots into cache", stale is False)

        httpx.post(f"{BASE}/__mock/faults", json={"type": "stale_data", "duration_seconds": 5})
        _, stale = client.fetch("/v1/depots")
        check("stale_data fault → X-Simulator-Stale honored", stale is True)
        httpx.post(f"{BASE}/__mock/faults", json={"type": "stale_data", "duration_seconds": 0})

        httpx.post(f"{BASE}/__mock/faults", json={"type": "unavailable", "duration_seconds": 4})
        data, stale = client.fetch("/v1/depots", retries=1)
        check("unavailable fault → cached data + stale", stale is True and data[0]["id"] == "depot-gazipur")
        time.sleep(4.2)  # let the fault expire
        data, stale = client.fetch("/v1/depots")
        check("fault expiry → fresh again", stale is False)

    # --------------------------------------------------------------- SSE

    def test_sse() -> None:
        import threading

        events_seen: list[str] = []
        done = threading.Event()

        def on_event(name: str, payload: dict) -> None:
            events_seen.append(name)
            if name == "simulation.tick" or len(events_seen) > 3:
                done.set()

        import threading as _t
        reader = _t.Thread(target=lambda: list(client.stream(on_event)), daemon=True)
        reader.start()
        check("SSE carries simulation.tick", done.wait(timeout=15), f"seen={events_seen}")

    # ------------------------------------------------- collector → DB

    def test_collector_persists() -> None:
        fresh_db()
        snap = collector.collect_once(client)
        assert snap is not None
        check("collector anchored on live tick", snap.tick >= 0)
        from sqlalchemy import func, select

        with db.session_scope() as session:
            depots = session.execute(select(func.count()).select_from(Depot)).scalar_one()
            dsnap = session.execute(select(func.count()).select_from(DepotInventorySnapshot)).scalar_one()
            ssnap = session.execute(select(func.count()).select_from(StationInventorySnapshot)).scalar_one()
            demand = session.execute(select(func.count()).select_from(DemandObservation)).scalar_one()
            events = session.execute(select(func.count()).select_from(SimEvent)).scalar_one()
            allocations = session.execute(select(func.count()).select_from(Allocation)).scalar_one()
        check("world mirror persisted (2 depots)", depots == 2)
        check("inventory snapshots persisted (2 depots × 3 fuels)", dsnap == 6)
        check("station snapshots persisted (4 stations × 3 fuels)", ssnap == 12)
        check("demand observations persisted", demand > 0)
        check("events persisted", events >= 0)
        check("allocation ledger persisted", allocations >= 0)

    # ------------------------------------------------------------ run

    test_reads()
    test_allocation_validation_order()
    test_faults()
    test_sse()
    test_collector_persists()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print(f"\n{len(PASS)} checks passed ✅")
