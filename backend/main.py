"""FastAPI entrypoint — Phase 3 scope.

Endpoint contracts match `web/src/lib/api/types.ts` (teammate's SvelteKit app):
- GET  /health                                     → HealthReport {status, components[]}
- GET  /api/state                                  → SimState (arrays, inventory merged in)
- GET  /api/alerts        → Alert[]                POST /api/alerts/{id}/ack → {ok}
- GET  /api/recommendations → Recommendation[]     (explanation flattened to string)
- POST /api/recommendations/{id}/approve|reject    → {ok: true}   (decisions.py)
- GET  /api/history → {decisions, allocations}     (simulator field names)
- GET  /api/logs → LogEntry[]                      (JSON log tail for the Logs tab)
- GET  /api/stream                                 → SSE live refresh

The collector loop runs in a background thread on startup (COLLECTOR_ENABLED=0
to disable).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from .db import get_engine, init_db
from .decisions import DecisionError, approve_recommendation, history, reject_recommendation
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


app = FastAPI(title="Fuel Supply Intelligence & Resilience Platform", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app)  # /metrics


def _worst(statuses: list[str]) -> str:
    if "DOWN" in statuses:
        return "DOWN"
    if "DEGRADED" in statuses:
        return "DEGRADED"
    return "HEALTHY"


# ---------------------------------------------------------------------------
# Health — HealthReport {status, components: [{component, status, latency_ms, detail, checked_at}]}
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    components: list[dict] = [{"component": "backend", "status": "HEALTHY", "latency_ms": 0, "detail": None, "checked_at": now}]

    t0 = time.monotonic()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components.append({"component": "db", "status": "HEALTHY",
                           "latency_ms": int((time.monotonic() - t0) * 1000), "detail": None, "checked_at": now})
    except Exception as exc:  # noqa: BLE001
        components.append({"component": "db", "status": "DOWN", "latency_ms": None,
                           "detail": str(exc)[:200], "checked_at": now})

    t0 = time.monotonic()
    try:
        data, _ = get_client().health()
        ok = data.get("status") == "ok"
        components.append({
            "component": "simulator",
            "status": "HEALTHY" if ok else "DEGRADED",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": json.dumps(data.get("simulation") or {}),
            "checked_at": now,
        })
    except Exception as exc:  # noqa: BLE001
        components.append({"component": "simulator", "status": "DOWN", "latency_ms": None,
                           "detail": str(exc)[:200], "checked_at": now})

    from .pipeline import _last_processed_tick

    last_tick = _last_processed_tick
    intel_status = "HEALTHY" if last_tick is not None else "DEGRADED"
    components.append({"component": "forecaster", "status": intel_status, "latency_ms": None,
                       "detail": f"last tick {last_tick}", "checked_at": now})
    components.append({"component": "planner", "status": intel_status, "latency_ms": None,
                       "detail": f"last tick {last_tick}", "checked_at": now})

    return {"status": _worst([c["status"] for c in components]), "components": components}


# ---------------------------------------------------------------------------
# SSE — event names match web/src/lib/api/sse.ts
# ---------------------------------------------------------------------------


@app.get("/api/stream")
async def stream(request: Request):
    from . import events as bus

    loop, q = bus.subscribe()

    async def gen():
        try:
            for event, data in bus.history():
                yield f"event: {event}\ndata: {data}\n\n"
            yield ": caught-up\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: {event}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe((loop, q))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# State — SimState (arrays; inventory/capacity merged into depot/station rows)
# ---------------------------------------------------------------------------


@app.get("/api/state")
def state() -> dict:
    from .collector import last_snapshot_meta
    from .models import (
        Depot, DepotInventorySnapshot, Region, Route, SimEvent, Station,
        StationInventorySnapshot, SupplyArrival,
    )

    with get_engine().connect() as conn:
        regions = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, name, demand_factor FROM regions"))]
        depots = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, name, region_id, status, dispatch_capacity_per_tick, capacity FROM depots"))]
        stations = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, name, region_id, status, demand_profile, demand_multiplier, capacity FROM stations"))]
        routes = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, source_depot_id, destination_station_id, transit_ticks, max_shipment, status FROM routes"))]
        arrivals = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, depot_id, fuel_type, quantity, planned_tick, actual_tick, status FROM supply_arrivals ORDER BY planned_tick"))]
        events = [dict(r._mapping) for r in conn.execute(
            text("SELECT id, type, start_tick, end_tick, status, parameters FROM sim_events ORDER BY id DESC"))]

        latest_tick = conn.execute(
            text("SELECT COALESCE(MAX(tick), 0) FROM station_inventory_snapshots")
        ).scalar_one()
        depot_inv = conn.execute(text(
            "SELECT s.depot_id, s.fuel_type, s.quantity FROM depot_inventory_snapshots s "
            "JOIN (SELECT depot_id, fuel_type, MAX(tick) AS mt FROM depot_inventory_snapshots "
            "      WHERE tick > :t - 50 GROUP BY depot_id, fuel_type) m "
            "  ON s.depot_id = m.depot_id AND s.fuel_type = m.fuel_type AND s.tick = m.mt"
        ), {"t": latest_tick}).mappings().all()
        station_inv = conn.execute(text(
            "SELECT s.station_id, s.fuel_type, s.quantity FROM station_inventory_snapshots s "
            "JOIN (SELECT station_id, fuel_type, MAX(tick) AS mt FROM station_inventory_snapshots "
            "      WHERE tick > :t - 50 GROUP BY station_id, fuel_type) m "
            "  ON s.station_id = m.station_id AND s.fuel_type = m.fuel_type AND s.tick = m.mt"
        ), {"t": latest_tick}).mappings().all()

    depot_inventory: dict[str, dict] = {}
    for r in depot_inv:
        depot_inventory.setdefault(r["depot_id"], {})[r["fuel_type"]] = r["quantity"]
    station_inventory: dict[str, dict] = {}
    for r in station_inv:
        station_inventory.setdefault(r["station_id"], {})[r["fuel_type"]] = r["quantity"]

    for d in depots:
        d["inventory"] = depot_inventory.get(d["id"], {})
    for s in stations:
        s["inventory"] = station_inventory.get(s["id"], {})

    meta = last_snapshot_meta
    return {
        "tick": meta.get("tick") or latest_tick,
        "sim_time": meta.get("sim_time") or "",
        "is_stale": bool(meta.get("is_stale", True)),
        "regions": regions,
        "depots": depots,
        "stations": stations,
        "routes": routes,
        "arrivals": arrivals,
        "events": events,
        "metrics": meta.get("metrics") or {},
    }


# ---------------------------------------------------------------------------
# Forecasts — latest-tick forecast + risk per station×fuel (UI drill-in)
# ---------------------------------------------------------------------------


@app.get("/api/forecasts")
def forecasts_endpoint() -> list[dict]:
    from sqlalchemy import text

    with get_engine().connect() as conn:
        latest_tick = conn.execute(
            text("SELECT COALESCE(MAX(generated_at_tick), 0) FROM forecasts")
        ).scalar_one()
        rows = conn.execute(text(
            "SELECT f.station_id, f.fuel_type, f.generated_at_tick, f.target_tick, "
            "f.predicted_liters, f.lower_bound, f.upper_bound, "
            "r.hours_to_stockout, r.stockout_probability, r.severity, r.confidence "
            "FROM forecasts f JOIN risk_assessments r "
            "  ON r.station_id = f.station_id AND r.fuel_type = f.fuel_type "
            " AND r.tick = f.generated_at_tick "
            "WHERE f.generated_at_tick = :t"
        ), {"t": latest_tick}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Demand — latest observed demand/served/unmet rows (Overview demand table)
# ---------------------------------------------------------------------------


@app.get("/api/demand")
def demand_endpoint() -> list[dict]:
    from sqlalchemy import text

    with get_engine().connect() as conn:
        # Use the latest tick with FULL per-tick coverage. The collector reads
        # each station's history at a slightly different moment while the world
        # keeps ticking, so the newest tick can be partially filled — a bare
        # MAX(tick) would render one station's rows as if it were the world.
        latest_tick = conn.execute(text(
            "SELECT COALESCE(MAX(tick), 0) FROM ("
            "  SELECT tick FROM demand_observations GROUP BY tick"
            "  HAVING COUNT(*) >= (SELECT COUNT(*) FROM stations) * 3"
            ")"
        )).scalar_one()
        rows = conn.execute(text(
            "SELECT station_id, fuel_type, demand_liters, served_liters, unmet_liters "
            "FROM demand_observations WHERE tick = :t ORDER BY station_id, fuel_type"
        ), {"t": latest_tick}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alerts — Alert[]
# ---------------------------------------------------------------------------


@app.get("/api/alerts")
def alerts_endpoint(limit: int = 100, status: str = "ALL") -> list[dict]:
    from sqlalchemy import select

    from .models import Alert

    limit = max(1, min(limit, 500))
    stmt = select(
        Alert.id, Alert.type, Alert.severity, Alert.station_id, Alert.fuel_type,
        Alert.message, Alert.status, Alert.created_tick,
    ).order_by(Alert.created_tick.desc(), Alert.id.desc()).limit(limit)
    if status and status != "ALL":
        stmt = stmt.where(Alert.status == status)
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [
        {
            **dict(r),
            "station_id": r["station_id"] or "",
            "fuel_type": r["fuel_type"] or "DIESEL",
        }
        for r in rows
    ]


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int) -> dict:
    from .models import Alert

    with get_engine().begin() as conn:
        row = conn.execute(text("SELECT id FROM alerts WHERE id = :id"), {"id": alert_id}).first()
        if row is None:
            raise HTTPException(404, detail=f"Alert {alert_id} not found")
        conn.execute(text("UPDATE alerts SET status = 'ACKED' WHERE id = :id"), {"id": alert_id})
        op_id = conn.execute(text(
            "INSERT INTO operators (name, role, password_hash) VALUES ('ops-console', 'operator', '') "
            "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id"
        )).scalar_one()
        conn.execute(text(
            "INSERT INTO audit_log (operator_id, action, entity_type, entity_id, payload, created_at) "
            "VALUES (:op, 'alert.acked', 'alert', :id, '{}', CURRENT_TIMESTAMP)"
        ), {"op": op_id, "id": str(alert_id)})
    from .events import publish

    publish("alert.acknowledged", {"id": alert_id})
    return {"ok": True, "id": alert_id, "status": "ACKED"}


# ---------------------------------------------------------------------------
# Recommendations — Recommendation[] (explanation flattened to text)
# ---------------------------------------------------------------------------


@app.get("/api/recommendations")
def recommendations_endpoint(status: str = "PROPOSED", limit: int = 30) -> list[dict]:
    from sqlalchemy import select

    from .models import Recommendation, RecommendationItem

    limit = max(1, min(limit, 100))
    with get_engine().connect() as conn:
        stmt = select(
            Recommendation.id, Recommendation.status, Recommendation.policy,
            Recommendation.confidence, Recommendation.risk_before, Recommendation.risk_after,
            Recommendation.explanation, Recommendation.alternatives,
        ).order_by(Recommendation.id.desc()).limit(limit)
        if status != "ALL":
            stmt = stmt.where(Recommendation.status == status)
        recs = conn.execute(stmt).mappings().all()
        rec_ids = [r["id"] for r in recs]
        items = conn.execute(select(
            RecommendationItem.id, RecommendationItem.recommendation_id,
            RecommendationItem.depot_id, RecommendationItem.station_id,
            RecommendationItem.route_id, RecommendationItem.fuel_type, RecommendationItem.quantity,
        ).where(RecommendationItem.recommendation_id.in_(rec_ids))).mappings().all() if rec_ids else []

    items_by_rec: dict[int, list[dict]] = {}
    for it in items:
        items_by_rec.setdefault(it["recommendation_id"], []).append(dict(it))

    out = []
    for r in recs:
        explanation = r["explanation"] or {}
        text_val = explanation.get("text") if isinstance(explanation, dict) else str(explanation)
        alternatives = r["alternatives"] or []
        out.append({
            "id": r["id"], "status": r["status"], "policy": r["policy"],
            "confidence": r["confidence"], "risk_before": r["risk_before"],
            "risk_after": r["risk_after"],
            "explanation": text_val or "",
            "alternatives": [a if isinstance(a, str) else json.dumps(a) for a in alternatives],
            "items": items_by_rec.get(r["id"], []),
        })
    return out


@app.post("/api/recommendations/{recommendation_id}/approve")
def approve_endpoint(recommendation_id: int, body: dict | None = None) -> dict:
    body = body or {}
    try:
        out = approve_recommendation(recommendation_id, note=body.get("note", ""), operator_name=body.get("operator"))
        return {"ok": True, **out}
    except DecisionError as exc:
        status = {"NOT_FOUND": 404, "INVALID_STATE": 409, "EXPIRED": 409,
                  "STALE_WORLD": 409, "SUBMISSION_FAILED": 409}.get(exc.code, 400)
        raise HTTPException(status, detail={"code": exc.code, "message": exc.message, **exc.detail})


@app.post("/api/recommendations/{recommendation_id}/reject")
def reject_endpoint(recommendation_id: int, body: dict | None = None) -> dict:
    body = body or {}
    try:
        out = reject_recommendation(recommendation_id, note=body.get("note", ""), operator_name=body.get("operator"))
        return {"ok": True, **out}
    except DecisionError as exc:
        status = {"NOT_FOUND": 404, "INVALID_STATE": 409}.get(exc.code, 400)
        raise HTTPException(status, detail={"code": exc.code, "message": exc.message, **exc.detail})


# ---------------------------------------------------------------------------
# History — {decisions: Decision[], allocations: Allocation[]} (simulator field names)
# ---------------------------------------------------------------------------


@app.get("/api/history")
def history_endpoint(
    limit: int = 100, recommendation_id: int | None = None,
    station_id: str | None = None, fuel_type: str | None = None,
) -> dict:
    result = history(limit=limit, recommendation_id=recommendation_id,
                     station_id=station_id, fuel_type=fuel_type)
    for d in result["decisions"]:
        d["decided_at"] = d["decided_at"].isoformat() if hasattr(d["decided_at"], "isoformat") else str(d["decided_at"])
    for a in result["allocations"]:
        a["source_depot_id"] = a.pop("depot_id", None)
        a["destination_station_id"] = a.pop("station_id", None)
    return result


# ---------------------------------------------------------------------------
# Logs — LogEntry[] (audit trail + system alerts, newest first)
# ---------------------------------------------------------------------------


@app.get("/api/logs")
def logs_endpoint(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    entries: list[dict] = []
    with get_engine().connect() as conn:
        audit = conn.execute(text(
            "SELECT a.created_at, a.action, a.entity_type, a.entity_id, a.payload, o.name AS operator "
            "FROM audit_log a LEFT JOIN operators o ON o.id = a.operator_id "
            "ORDER BY a.id DESC LIMIT :lim"
        ), {"lim": limit}).mappings().all()
        for r in audit:
            entries.append({
                "ts": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                "level": "INFO",
                "component": "decisions",
                "message": f"{r['action']} {r['entity_type']}#{r['entity_id']}"
                           + (f" by {r['operator']}" if r["operator"] else ""),
                "data": r["payload"] or {},
            })
        sys_alerts = conn.execute(text(
            "SELECT created_tick, severity, message FROM alerts WHERE type = 'system' "
            "ORDER BY id DESC LIMIT :lim"
        ), {"lim": limit}).mappings().all()
        for r in sys_alerts:
            entries.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "ERROR" if r["severity"] in ("HIGH", "CRITICAL") else "WARN",
                "component": "collector",
                "message": r["message"],
                "data": {"tick": r["created_tick"]},
            })
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries[:limit]
