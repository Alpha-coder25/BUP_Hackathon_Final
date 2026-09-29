"""Intelligence pipeline: per-tick forecast → anomaly → optimizer → explainer.

Wire-up of `DOCS/BackendImplementation.md` §4 modules into the flow drawn in
`DOCS/ApplicationFlow.md` (continuous loop). Per tick:

  WorldSnapshot → forecasts (P10/P50/P90 per station×fuel)
               → risk assessments (hours_to_stockout, Monte Carlo probability)
               → anomaly rules → alerts (deduped per tick)
               → LP over open routes → recommendation + items
               → GenAI facts → 3-sentence explanation
               → all persisted (forecasts, risk_assessments, alerts,
                 recommendations, recommendation_items, model_versions)

Debounced: runs at most once per simulator tick (SSE thread + poll loop may
both call it; the pipeline tracks the last processed tick).
"""

from __future__ import annotations

import logging
import threading

import pandas as pd
from sqlalchemy import select

from . import anomaly, explainer, forecast, optimizer
from .collector import WorldSnapshot
from .db import session_scope
from .models import (
    Alert,
    Forecast,
    ModelVersion,
    Recommendation,
    RecommendationItem,
    RiskAssessment,
)

log = logging.getLogger(__name__)

TICK_MINUTES = 15
REC_VALID_TICKS = 16         # 4 simulated hours — long enough to actually click Approve
ALERT_DEDUPE_WINDOW_TICKS = 4

_last_processed_tick: int | None = None
_tick_lock = threading.Lock()
_alerted_events: set[int] = set()  # crisis events already alerted (process lifetime)


def reset_pipeline_state() -> None:
    """Test hook: clear the tick debounce + crisis alert memory."""
    global _last_processed_tick
    with _tick_lock:
        _last_processed_tick = None
    _alerted_events.clear()


def _demand_frames(snap: WorldSnapshot) -> dict[tuple[str, str], pd.DataFrame]:
    """Per station×fuel history as a DataFrame for the forecaster."""
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for station_id, rows in snap.demand_history.items():
        by_fuel: dict[str, list[dict]] = {}
        for row in rows:
            by_fuel.setdefault(row.get("fuel_type", ""), []).append(row)
        for fuel, fuel_rows in by_fuel.items():
            df = pd.DataFrame(fuel_rows)
            if {"tick", "sim_time", "demand_liters"} <= set(df.columns):
                frames[(station_id, fuel)] = df
    return frames


def _station_rows(snap: WorldSnapshot) -> dict[str, dict]:
    return {s.get("id"): s for s in snap.stations if s.get("id")}


def _depot_rows(snap: WorldSnapshot) -> dict[str, dict]:
    return {d.get("id"): d for d in snap.depots if d.get("id")}


def _incoming_liters(snap: WorldSnapshot, station_id: str) -> float:
    """In-flight supply headed to this station (liters).
    supply_arrivals deliver to depots, not stations — only depot→station
    allocations count as station-incoming."""
    return sum(
        float(alloc.get("quantity") or 0.0)
        for alloc in snap.allocations
        if alloc.get("destination_station_id") == station_id
        and alloc.get("status") in ("PENDING", "IN_TRANSIT")
    )


def run_pipeline(snap: WorldSnapshot) -> None:
    """Full intelligence pass for one tick. Idempotent per tick (debounced);
    never raises — every stage degrades per TRD §7."""
    global _last_processed_tick

    with _tick_lock:
        if _last_processed_tick == snap.tick:
            return
        _last_processed_tick = snap.tick

    tick = snap.tick
    stations = _station_rows(snap)
    depots = _depot_rows(snap)
    demand_frames = _demand_frames(snap)

    alerts: list[anomaly.AnomalyAlert] = []

    # Per station×fuel: forecast → risk
    forecast_rows: list[dict] = []
    risk_rows: list[dict] = []
    needs: list[optimizer.StationNeed] = []
    risk_before: dict[tuple[str, str], float] = {}

    for (station_id, fuel), history in demand_frames.items():
        station = stations.get(station_id, {})
        inventory = float((station.get("inventory") or {}).get(fuel, 0.0))
        incoming = _incoming_liters(snap, station_id)
        point = forecast.forecast_station_fuel(
            station_id=station_id,
            fuel_type=fuel,
            history=history,
            inventory_liters=inventory,
            incoming_liters=incoming,
            target_tick=tick + 1,
            target_sim_time=_next_sim_time(snap.sim_time),
            tick_minutes=TICK_MINUTES,
        )
        forecast_rows.append(point)
        risk_rows.append(point)
        risk_before[(station_id, fuel)] = point.stockout_probability
        needs.append(
            optimizer.StationNeed(
                destination_station_id=station_id,
                fuel_type=fuel,
                inventory=inventory,
                incoming=incoming,
                p50_per_tick=point.predicted_liters,
                p90_per_tick=point.upper_bound,
                station_capacity=float((station.get("capacity") or {}).get(fuel, 10**9)),
            )
        )

    # Crisis recompute path (ApplicationFlow.md): ACTIVE events raise an alert
    # and adjust model inputs before the LP → "Recovery plan" recommendation.
    crisis_multipliers = _crisis_demand_multipliers(snap)
    if crisis_multipliers:
        for n in needs:
            m = crisis_multipliers.get(n.destination_station_id, 1.0)
            if m != 1.0:
                n.p50_per_tick *= m
                n.p90_per_tick *= m
    needs = [n for n in needs if stations.get(n.destination_station_id, {}).get("status") != "OUTAGE"]

    # Anomaly rules (inventory before/after across this tick's snapshots)
    station_inventory_before = _inventory_before(snap)
    station_inventory_now = {
        (s["id"], fuel): float(level)
        for s in snap.stations
        for fuel, level in (s.get("inventory") or {}).items()
    }
    expected_draw = {
        key: point.predicted_liters * crisis_multipliers.get(key[0], 1.0)
        for key, point in zip(
            [(p.station_id, p.fuel_type) for p in forecast_rows], forecast_rows
        )
    }
    alerts = anomaly.evaluate(
        tick=tick,
        demand_history={
            key: df["demand_liters"].tolist() for key, df in demand_frames.items()
        },
        stations=snap.stations,
        station_inventory_before=station_inventory_before,
        station_inventory_now=station_inventory_now,
        expected_draw=expected_draw,
        supply_arrivals=snap.supply_arrivals,
    )

    # Optimizer over open routes
    rec: optimizer.Recommendation | None = None
    if needs:
        route_options = _expand_routes_per_fuel(snap, needs)
        depot_fuel_stock = {
            (d_id, fuel): float((d.get("inventory") or {}).get(fuel, 0.0))
            for d_id, d in depots.items()
            for fuel in {n.fuel_type for n in needs}
        }
        dispatch = {
            d_id: float(d.get("dispatch_capacity_per_tick", 0) or 0)
            for d_id, d in depots.items()
        }
        try:
            rec = optimizer.optimize(
                depot_fuel_stock=depot_fuel_stock,
                depot_dispatch_capacity=dispatch,
                needs=needs,
                routes=route_options,
                risk_before=risk_before,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to heuristic (TRD §7)
            log.warning("optimizer raised (%s); running heuristic", exc)
            try:
                rec = optimizer.heuristic_plan(depot_fuel_stock, needs, route_options, risk_before)
            except Exception:  # noqa: BLE001
                rec = None

    # GenAI explanation (facts only) — anchored on the highest-risk need.
    worst = max(needs, key=lambda n: risk_before.get(n.key, 0.0), default=None)
    explanation = explainer.explain({
        "tick": tick,
        "station_id": worst.destination_station_id if worst else None,
        "fuel_type": worst.fuel_type if worst else None,
        "risk_before": rec.risk_before if rec else None,
        "policy": rec.policy if rec else None,
        "hours_to_stockout": min(
            (p.hours_to_stockout for p in risk_rows if p.hours_to_stockout is not None),
            default=None,
        ),
        "items": [i.__dict__ for i in (rec.items if rec else [])][:5],
        "cause": _cause(alerts),
    })

    alerts.extend(_crisis_alerts(snap))

    # Persist everything in one transaction
    persisted_rec_id: int | None = None
    try:
        with session_scope() as session:
            # Expire stale PROPOSED cards so the feed stays meaningful.
            stale = session.execute(
                select(Recommendation.id).where(
                    Recommendation.status == "PROPOSED",
                    Recommendation.expires_tick < tick,
                )
            ).scalars().all()
            if stale:
                session.query(Recommendation).filter(Recommendation.id.in_(stale)).update(
                    {Recommendation.status: "EXPIRED"}, synchronize_session=False
                )
            mv_id = _ensure_model_version(session)
            for point in forecast_rows:
                session.add(Forecast(
                    station_id=point.station_id,
                    model_version_id=mv_id,
                    fuel_type=point.fuel_type,
                    generated_at_tick=tick,
                    target_tick=point.target_tick,
                    predicted_liters=point.predicted_liters,
                    lower_bound=point.lower_bound,
                    upper_bound=point.upper_bound,
                ))
                session.add(RiskAssessment(
                    station_id=point.station_id,
                    model_version_id=mv_id,
                    fuel_type=point.fuel_type,
                    tick=tick,
                    hours_to_stockout=point.hours_to_stockout,
                    stockout_probability=point.stockout_probability,
                    severity=point.severity,
                    confidence=point.confidence,
                    signals=point.signals,
                ))
            _persist_alerts(session, alerts)
            if rec is not None and rec.items:
                rec_row = Recommendation(
                    policy=rec.policy,
                    tick=tick,
                    status="PROPOSED",
                    confidence=rec.confidence,
                    risk_before=rec.risk_before,
                    risk_after=rec.risk_after,
                    explanation=explanation,
                    alternatives=[],
                    expires_tick=tick + REC_VALID_TICKS,
                )
                session.add(rec_row)
                session.flush()
                for item in rec.items:
                    session.add(RecommendationItem(
                        recommendation_id=rec_row.id,
                        depot_id=item.source_depot_id,
                        station_id=item.destination_station_id,
                        route_id=item.route_id,
                        fuel_type=item.fuel_type,
                        quantity=item.quantity,
                    ))
                persisted_rec_id = rec_row.id
        log.info(
            "pipeline tick=%s forecasts=%d alerts=%d rec_items=%d",
            tick, len(forecast_rows), len(alerts), len(rec.items) if rec else 0,
        )
        try:
            from .events import publish

            if persisted_rec_id is not None:
                publish("recommendation.created", {  # noqa: pipeline → dashboard
                    "recommendation_id": persisted_rec_id,
                    "tick": tick, "items": len(rec.items),
                    "risk_before": rec.risk_before, "risk_after": rec.risk_after,
                })
            if alerts:
                publish("alert.raised", {"tick": tick, "count": len(alerts)})
        except Exception:  # noqa: BLE001 — UI updates must never break the pipeline
            pass
    except Exception as exc:  # noqa: BLE001 — pipeline survives a DB blip
        log.exception("pipeline persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_sim_time(sim_time: str) -> str:
    try:
        ts = pd.Timestamp(sim_time) + pd.Timedelta(minutes=TICK_MINUTES)
        return ts.isoformat()
    except Exception:  # noqa: BLE001
        return sim_time


def _inventory_before(snap: WorldSnapshot) -> dict[tuple[str, str], float]:
    """Previous tick's station inventory from... the snapshot itself is 'now'.
    We approximate 'before' from the current inventory minus observed demand —
    good enough for drop detection until history queries land in the pipeline."""
    before: dict[tuple[str, str], float] = {}
    for s in snap.stations:
        for fuel, level in (s.get("inventory") or {}).items():
            hist = snap.demand_history.get(s["id"]) or []
            latest = next(
                (r.get("demand_liters", 0.0) for r in reversed(hist) if r.get("fuel_type") == fuel),
                0.0,
            )
            before[(s["id"], fuel)] = float(level) + float(latest)
    return before


def _crisis_demand_multipliers(snap: WorldSnapshot) -> dict[str, float]:
    """demand_spike events → per-station multiplier (region_ids/station_ids filters,
    empty = all stations — guide §7.8)."""
    multipliers: dict[str, float] = {}
    for event in snap.active_events():
        if event.get("type") != "demand_spike":
            continue
        params = event.get("parameters") or {}
        m = float(params.get("multiplier", 1.5))
        station_ids = params.get("station_ids") or []
        region_ids = set(params.get("region_ids") or [])
        for s in snap.stations:
            if station_ids and s.get("id") not in station_ids:
                continue
            if region_ids and s.get("region_id") not in region_ids:
                continue
            multipliers[s["id"]] = multipliers.get(s["id"], 1.0) * m
    return multipliers


def _crisis_alerts(snap: WorldSnapshot) -> list[anomaly.AnomalyAlert]:
    """One alert per ACTIVE crisis event (once per event per process)."""
    out: list[anomaly.AnomalyAlert] = []
    for event in snap.active_events():
        eid = event.get("id")
        if eid in _alerted_events:
            continue
        _alerted_events.add(eid)
        etype = event.get("type", "unknown")
        severity = "CRITICAL" if etype in ("station_outage", "supply_shortfall") else "HIGH"
        out.append(anomaly.AnomalyAlert(
            type="disruption",
            severity=severity,
            station_id=None,
            fuel_type=None,
            message=(
                f"Crisis {etype} event#{eid} ACTIVE (ticks {event.get('start_tick')}–"
                f"{event.get('end_tick')}) — recomputing forecasts and recovery plan"
            ),
            created_tick=snap.tick,
        ))
    return out


def _cause(alerts: list[anomaly.AnomalyAlert]) -> str | None:
    if not alerts:
        return None
    kinds = {a.message.split(":")[0].lower() for a in alerts}
    return " and ".join(sorted(kinds))[:200]


def _persist_alerts(session, alerts: list[anomaly.AnomalyAlert]) -> None:
    """Dedupe: skip a rule-firing alert of the same type+station+fuel within the window
    (both against DB rows and within this batch)."""
    if not alerts:
        return
    cutoff = (alerts[0].created_tick or 0) - ALERT_DEDUPE_WINDOW_TICKS
    existing = session.execute(
        select(Alert.type, Alert.station_id, Alert.fuel_type).where(
            Alert.created_tick >= cutoff, Alert.status == "OPEN"
        )
    ).all()
    seen = set(existing)
    added = 0
    for a in alerts:
        key = (a.type, a.station_id, a.fuel_type)
        if key in seen:
            continue
        seen.add(key)
        session.add(Alert(
            type=a.type,
            severity=a.severity,
            station_id=a.station_id,
            fuel_type=a.fuel_type,
            message=a.message,
            created_tick=a.created_tick,
        ))
        added += 1
    if added == 0:
        log.debug("alerts deduped at tick=%s", alerts[0].created_tick)


def _ensure_model_version(session) -> int:
    row = session.execute(
        select(ModelVersion).where(ModelVersion.name == "quantile_gbm", ModelVersion.is_active.is_(True))
    ).scalar_one_or_none()
    if row is None:
        row = ModelVersion(name="quantile_gbm", kind="forecast", version="1.0.0", params={
            "features": ["hour", "dow", "lag1", "roll6"],
            "quantiles": [0.1, 0.5, 0.9],
            "min_history": forecast.MIN_HISTORY_ROWS,
        })
        session.add(row)
        session.flush()
        return row.id
    return row.id


def _expand_routes_per_fuel(snap: WorldSnapshot, needs: list[optimizer.StationNeed]) -> list[optimizer.RouteOption]:
    """One RouteOption per (route, fuel) — the LP keys depot stock per fuel.
    Synthetic route ids ('route-x::DIESEL') are expanded back to real route ids
    at submit time."""
    fuels = {n.fuel_type for n in needs}
    options: list[optimizer.RouteOption] = []
    for r in snap.routes:
        if r.get("status") != "AVAILABLE":
            continue
        for fuel in fuels:
            options.append(
                optimizer.RouteOption(
                    route_id=f"{r['id']}::{fuel}",  # synthetic id: route×fuel
                    source_depot_id=r["source_depot_id"],
                    destination_station_id=r["destination_station_id"],
                    max_shipment=float(r.get("max_shipment", 0)),
                    cost_per_liter=1.0,
                    transit_ticks=int(r.get("transit_ticks", 1)),
                )
            )
    return options
