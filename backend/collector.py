"""Collector loop: poll the simulator on tick, validate, persist snapshots.

Contract: `DOCS/BackendImplementation.md` §3, `DOCS/ApplicationFlow.md` (continuous loop),
simulator guide §6 (SSE is advisory; REST is truth).

Flow per tick:
  trigger (SSE simulation.tick | 30s poll fallback)
    → re-GET world reads via SimulatorClient (retry/cache/stale handled there)
    → validate + persist (world mirror upserts, append-only snapshot rows)
    → hand off to the intelligence pipeline
    → ingest ACTIVE events → crisis recompute (§7)

Persistence notes:
- World mirror tables (regions/depots/stations/routes/supply_arrivals/sim_events)
  are **upserted** — they mirror current simulator state.
- Snapshot tables (depot/station inventory, demand observations) are **append-only**
  keyed by tick; re-collecting the same tick is a no-op (idempotent).
- `sync_allocation_status` updates the local ledger from SSE
  `allocation.status_changed` payloads (full allocation object per guide §6.3).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
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
from .simulator_client import (
    SSE_EVENTS_TO_PATHS,
    SimulatorClient,
    get_client,
)

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = float(os.getenv("COLLECTOR_POLL_SECONDS", "30"))

# Last snapshot metadata for /api/state (tick + staleness at collection time).
last_snapshot_meta: dict = {"tick": None, "is_stale": True, "sim_time": "", "metrics": {}}


class WorldSnapshot:
    """In-memory image of one tick's world; maps to the ERD snapshot tables."""

    def __init__(self, tick: int, sim_time: str, is_stale: bool = False):
        self.tick = tick
        self.sim_time = sim_time
        self.is_stale = is_stale
        self.collected_at = datetime.now(timezone.utc).isoformat()
        self.regions: list[dict] = []
        self.depots: list[dict] = []
        self.stations: list[dict] = []
        self.routes: list[dict] = []
        self.supply_arrivals: list[dict] = []
        self.events: list[dict] = []
        self.allocations: list[dict] = []
        self.metrics: dict = {}
        self.demand_history: dict[str, list[dict]] = {}  # station_id → rows

    def active_events(self) -> list[dict]:
        """Crisis handling input: ACTIVE events drive the recompute path."""
        return [e for e in self.events if e.get("status") == "ACTIVE"]

    def open_routes(self) -> list[dict]:
        """Routes usable by the optimizer right now (crisis may remove some)."""
        return [r for r in self.routes if r.get("status") == "AVAILABLE"]


def raise_system_alert(component: str, detail: str) -> None:
    """Bad data / degraded component → alerts table + JSON log. Never crash."""
    # DB write is best-effort here: the collector must survive a DB outage.
    try:
        from .models import Alert
        from .db import session_scope

        with session_scope() as session:
            session.add(
                Alert(
                    type="system",
                    severity="HIGH",
                    message=f"[{component}] {detail}"[:500],
                    created_tick=-1,
                )
            )
    except Exception:  # noqa: BLE001 — logging must never be the thing that dies
        log.error("system_alert component=%s detail=%s", component, detail)


def _parse_sim_time(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Persistence — world mirror upserts
# ---------------------------------------------------------------------------


def _upsert_regions(session: Session, rows: list[dict]) -> None:
    for r in rows:
        session.merge(Region(id=r["id"], name=r.get("name", ""), demand_factor=r.get("demand_factor", 1.0)))


def _upsert_depots(session: Session, rows: list[dict]) -> None:
    for d in rows:
        session.merge(
            Depot(
                id=d["id"],
                region_id=d.get("region_id", ""),
                name=d.get("name", ""),
                status=d.get("status", "OPEN"),
                dispatch_capacity_per_tick=int(d.get("dispatch_capacity_per_tick", 0)),
                capacity=d.get("capacity", {}),
            )
        )


def _upsert_stations(session: Session, rows: list[dict]) -> None:
    for s in rows:
        session.merge(
            Station(
                id=s["id"],
                region_id=s.get("region_id", ""),
                name=s.get("name", ""),
                demand_profile=s.get("demand_profile", ""),
                status=s.get("status", "OPEN"),
                demand_multiplier=float(s.get("demand_multiplier", 1.0)),
                capacity=s.get("capacity", {}),
            )
        )


def _upsert_routes(session: Session, rows: list[dict]) -> None:
    for r in rows:
        session.merge(
            Route(
                id=r["id"],
                source_depot_id=r.get("source_depot_id", ""),
                destination_station_id=r.get("destination_station_id", ""),
                transit_ticks=int(r.get("transit_ticks", 0)),
                max_shipment=int(r.get("max_shipment", 0)),
                status=r.get("status", "AVAILABLE"),
            )
        )


def _upsert_supply_arrivals(session: Session, rows: list[dict]) -> None:
    for a in rows:
        session.merge(
            SupplyArrival(
                id=str(a["id"]),
                depot_id=a.get("depot_id", ""),
                fuel_type=a.get("fuel_type", ""),
                quantity=float(a.get("quantity", 0.0)),
                planned_tick=int(a.get("planned_tick", 0)),
                actual_tick=a.get("actual_tick"),
                status=a.get("status", "SCHEDULED"),
            )
        )


def _upsert_sim_events(session: Session, rows: list[dict]) -> None:
    for e in rows:
        session.merge(
            SimEvent(
                id=int(e["id"]),
                type=e.get("type", ""),
                start_tick=int(e.get("start_tick", 0)),
                end_tick=int(e.get("end_tick", 0)),
                status=e.get("status", "SCHEDULED"),
                parameters=e.get("parameters", {}),
            )
        )


# ---------------------------------------------------------------------------
# Persistence — append-only snapshots (idempotent per tick)
# ---------------------------------------------------------------------------


def _insert_conflictless(session: Session, model, values: dict, conflict_cols: tuple[str, ...]) -> None:
    """Atomic append: INSERT … ON CONFLICT DO NOTHING. Race-proof across the
    SSE and poll threads (existence-check-then-insert is not)."""
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    session.execute(
        dialect_insert(model).values(**values).on_conflict_do_nothing(
            index_elements=list(conflict_cols)
        )
    )


def _append_depot_snapshots(session: Session, snap: WorldSnapshot) -> None:
    for d in snap.depots:
        for fuel, quantity in (d.get("inventory") or {}).items():
            _insert_conflictless(
                session,
                DepotInventorySnapshot,
                {
                    "depot_id": d["id"],
                    "tick": snap.tick,
                    "sim_time": _parse_sim_time(snap.sim_time),
                    "fuel_type": fuel,
                    "quantity": float(quantity),
                },
                ("depot_id", "tick", "fuel_type"),
            )


def _append_station_snapshots(session: Session, snap: WorldSnapshot) -> None:
    for s in snap.stations:
        for fuel, quantity in (s.get("inventory") or {}).items():
            _insert_conflictless(
                session,
                StationInventorySnapshot,
                {
                    "station_id": s["id"],
                    "tick": snap.tick,
                    "sim_time": _parse_sim_time(snap.sim_time),
                    "fuel_type": fuel,
                    "quantity": float(quantity),
                },
                ("station_id", "tick", "fuel_type"),
            )


def _append_demand_observations(session: Session, snap: WorldSnapshot) -> None:
    for station_id, rows in snap.demand_history.items():
        for row in rows:
            tick = int(row.get("tick", snap.tick))
            fuel = row.get("fuel_type", "")
            _insert_conflictless(
                session,
                DemandObservation,
                {
                    "station_id": row.get("station_id", station_id),
                    "fuel_type": fuel,
                    "tick": tick,
                    "demand_liters": float(row.get("demand_liters", 0.0)),
                    "served_liters": float(row.get("served_liters", 0.0)),
                    "unmet_liters": float(row.get("unmet_liters", 0.0)),
                },
                ("station_id", "fuel_type", "tick"),
            )


# ---------------------------------------------------------------------------
# Allocation ledger sync (SSE allocation.status_changed → DB)
# ---------------------------------------------------------------------------


def sync_allocation_status(session: Session, payload: dict) -> None:
    """Upsert one allocation from the simulator's ledger object (guide §6.3:
    SSE carries the full serialized allocation). Keyed on idempotency_key."""
    key = payload.get("idempotency_key")
    if not key:
        raise_system_alert("collector", f"allocation payload without idempotency_key: {payload!r}")
        return
    existing = session.execute(
        select(Allocation).where(Allocation.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is None:
        existing = Allocation(
            idempotency_key=key,
            depot_id=payload.get("source_depot_id", ""),
            station_id=payload.get("destination_station_id", ""),
            route_id=payload.get("route_id", ""),
            fuel_type=payload.get("fuel_type", ""),
            quantity=float(payload.get("quantity", 0.0)),
        )
        session.add(existing)
    existing.sim_allocation_id = payload.get("id")
    existing.status = payload.get("status", existing.status)
    existing.created_tick = payload.get("created_tick", existing.created_tick)
    existing.departure_tick = payload.get("departure_tick", existing.departure_tick)
    existing.expected_arrival_tick = payload.get("expected_arrival_tick", existing.expected_arrival_tick)
    existing.actual_arrival_tick = payload.get("actual_arrival_tick", existing.actual_arrival_tick)
    existing.failure_reason = payload.get("failure_reason", existing.failure_reason)


def sync_all_allocations(session: Session, rows: list[dict]) -> None:
    for payload in rows:
        sync_allocation_status(session, payload)


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

_STALE_NONE = object()


def collect_tick(client: SimulatorClient | None = None) -> WorldSnapshot | None:
    """One collection pass. Returns None when there is no anchor data at all
    (first run, simulator unreachable — UI must show 'no data', not zeros)."""
    client = client or get_client()
    snap = WorldSnapshot(tick=-1, sim_time="", is_stale=False)
    results: dict[str, tuple[object, bool]] = {}
    fetches = {
        "instance": client.instance,
        "regions": client.regions,
        "depots": client.depots,
        "stations": client.stations,
        "routes": client.routes,
        "supply_arrivals": client.supply_arrivals,
        "events": client.events,
        "allocations": client.allocations,
        "metrics": client.metrics,
    }
    for label, fn in fetches.items():
        try:
            results[label] = fn()
        except Exception as exc:  # noqa: BLE001 — degraded, not dead
            raise_system_alert("collector", f"{label} failed: {exc}")
            results[label] = (_STALE_NONE, True)

    instance = results["instance"][0]
    if instance is _STALE_NONE or instance is None:
        return None  # no instance → nothing to anchor the snapshot on
    snap.tick = int(instance.get("tick", -1))
    snap.sim_time = str(instance.get("sim_time", ""))
    snap.is_stale = results["instance"][1]

    for label in ("regions", "depots", "stations", "routes", "supply_arrivals", "events", "allocations"):
        data, stale = results[label]
        if data is not _STALE_NONE:
            setattr(snap, label, list(data))
        snap.is_stale = snap.is_stale or stale
    metrics, stale = results["metrics"]
    if metrics is not _STALE_NONE:
        snap.metrics = metrics or {}
    snap.is_stale = snap.is_stale or stale

    # demand history grows unboundedly — recent window per station only
    for station in snap.stations:
        station_id = station.get("id")
        if not station_id:
            continue
        try:
            rows, stale = client.demand_history(station_id)
            snap.demand_history[station_id] = rows
            snap.is_stale = snap.is_stale or stale
        except Exception as exc:  # noqa: BLE001
            raise_system_alert("collector", f"demand-history:{station_id} failed: {exc}")

    if snap.is_stale:
        log.warning("collector: stale data at tick=%s", snap.tick)
    return snap


def persist_snapshot(session: Session, snap: WorldSnapshot) -> None:
    """Write one snapshot set: mirror upserts + append-only tick rows."""
    _upsert_regions(session, snap.regions)
    _upsert_depots(session, snap.depots)
    _upsert_stations(session, snap.stations)
    _upsert_routes(session, snap.routes)
    _upsert_supply_arrivals(session, snap.supply_arrivals)
    _upsert_sim_events(session, snap.events)
    _append_depot_snapshots(session, snap)
    _append_station_snapshots(session, snap)
    _append_demand_observations(session, snap)
    sync_all_allocations(session, snap.allocations)


def run_pipeline(snapshot: WorldSnapshot) -> None:
    """Hand the snapshot to the intelligence pipeline (forecast → anomaly →
optimizer → explainer, BackendImplementation.md §4). Debounced per tick
    inside pipeline.run_pipeline; failures degrade, never kill the loop."""
    try:
        from .pipeline import run_pipeline as _run

        _run(snapshot)
    except Exception:  # noqa: BLE001 — the collector outlives any pipeline failure
        log.exception("pipeline failed at tick=%s", snapshot.tick)


def collect_once(client: SimulatorClient | None = None) -> WorldSnapshot | None:
    """collect → persist → enqueue. The unit of work for both loop drivers."""
    snap = collect_tick(client)
    if snap is None:
        return None
    try:
        from .db import session_scope

        with session_scope() as session:
            persist_snapshot(session, snap)
    except Exception as exc:  # noqa: BLE001 — persistence failure must not kill the loop
        raise_system_alert("collector", f"persist failed: {exc}")
        return snap
    # Pipeline for this tick runs in whichever thread persisted it; the other
    # thread's persist becomes a no-op via ON CONFLICT, and run_pipeline
    # debounces per tick. Both drivers may call harmlessly.
    run_pipeline(snap)
    last_snapshot_meta.update({
        "tick": snap.tick, "is_stale": snap.is_stale,
        "sim_time": snap.sim_time, "metrics": snap.metrics,
    })
    try:
        from .events import publish

        # Dashboard SSE event names match the frontend contract (sse.ts):
        publish("simulation.tick", {"tick": snap.tick, "sim_time": snap.sim_time})
    except Exception:  # noqa: BLE001 — UI updates must never break collection
        pass
    return snap


# ---------------------------------------------------------------------------
# Drivers: poll loop (always) + SSE thread (fast trigger)
# ---------------------------------------------------------------------------

def _sse_listener(stop: threading.Event) -> None:
    """SSE → immediate collect. Events are hints; collect_tick re-GETs REST."""
    client = get_client()

    def on_event(name: str, payload: dict) -> None:
        if name == "allocation.status_changed":
            try:
                from .db import session_scope

                with session_scope() as session:
                    sync_allocation_status(session, payload)
                try:
                    from .events import publish

                    publish("allocation.status_changed", payload)
                except Exception:  # noqa: BLE001
                    pass
                return  # ledger sync only — no full re-collect needed
            except Exception as exc:  # noqa: BLE001
                log.exception("allocation sync failed: %s", exc)
        if name in SSE_EVENTS_TO_PATHS or name == "__reconnected__":
            try:
                collect_once(client)
            except Exception as exc:  # noqa: BLE001
                log.exception("sse-triggered collect failed: %s", exc)

    for _ in client.stream(on_event):
        if stop.is_set():
            return


def run_forever() -> None:
    """Blocking poll loop + SSE trigger thread. Entry point for the worker."""
    stop = threading.Event()
    threading.Thread(target=_sse_listener, args=(stop,), daemon=True).start()
    log.info("collector: poll every %ss, SSE triggers active", POLL_INTERVAL_SECONDS)
    try:
        while True:
            try:
                collect_once()
            except Exception:  # noqa: BLE001 — the loop outlives any single failure
                log.exception("collector pass failed")
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever()
