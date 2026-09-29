"""Pipeline tests — anomaly rules, explainer, full pipeline persistence.

Run:  .venv/bin/python backend/tests/test_pipeline.py
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import anomaly, db, explainer, pipeline  # noqa: E402
from backend.collector import WorldSnapshot  # noqa: E402
from backend.models import (  # noqa: E402
    Alert,
    Forecast,
    Recommendation,
    RecommendationItem,
    RiskAssessment,
)
from backend.simulator_client import SimulatorClient  # noqa: E402

PASS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail and not cond else ''}")
    PASS.append(name)
    assert cond, f"{name} {detail}"


def fresh_db() -> None:
    for attr in ("_engine", "_SessionLocal"):
        setattr(db, attr, None)
    db.DB_URL = f"sqlite:///tmp-pipeline-{uuid.uuid4().hex}.db"
    db.init_db()


# ---------------------------------------------------------------------------
# explainer
# ---------------------------------------------------------------------------

def test_template_explanation() -> None:
    facts = {
        "station_id": "station-mirpur", "fuel_type": "DIESEL",
        "hours_to_stockout": 6.2, "risk_before": 0.72, "policy": "optimizer",
        "items": [{"quantity": 5000, "fuel_type": "DIESEL", "source_depot_id": "depot-gazipur",
                   "route_id": "route-gazipur-mirpur"}],
        "cause": "demand spike",
    }
    out = explainer.explain(facts, use_llm=False)
    check("template source", out["source"] == "template")
    text = out["text"]
    check("3 sentences", text.count(". ") == 2 and text.endswith("."), text)
    check("mentions station", "station-mirpur" in text)
    check("mentions risk", "72%" in text, text)


# ---------------------------------------------------------------------------
# anomaly rules
# ---------------------------------------------------------------------------

def test_spike_rule() -> None:
    calm = [100.0] * 30
    check("flat history → no spike", not anomaly.demand_spike(calm, 100.0))
    check("3σ jump → spike", anomaly.demand_spike(calm, 400.0))
    check("short history → no verdict", not anomaly.demand_spike([100.0] * 3, 1000.0))


def test_drop_rule() -> None:
    check("expected draw → no drop", not anomaly.inventory_drop(1000, 900, 100))
    check("excess drop → drop", anomaly.inventory_drop(1000, 500, 100))


def test_delay_rule() -> None:
    check("DELAYED status → delay", anomaly.shipment_delay({"status": "DELAYED"}, 10))
    check("late arrival → delay", anomaly.shipment_delay({"status": "SCHEDULED", "planned_tick": 5}, 10))
    check("on-time → no delay", not anomaly.shipment_delay({"status": "SCHEDULED", "planned_tick": 9}, 10))


# ---------------------------------------------------------------------------
# pipeline end-to-end on a mock snapshot
# ---------------------------------------------------------------------------

def _snapshot(tick: int, diesel: float, demand: list[float]) -> WorldSnapshot:
    snap = WorldSnapshot(tick=tick, sim_time=f"2026-01-01T{tick // 4:02d}:{(tick % 4) * 15:02d}:00+00:00")
    snap.depots = [{
        "id": "depot-gazipur", "region_id": "region-dhaka", "name": "Gazipur", "status": "OPEN",
        "dispatch_capacity_per_tick": 12000,
        "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000},
        "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
    }]
    snap.stations = [{
        "id": "station-mirpur", "region_id": "region-dhaka", "name": "Mirpur",
        "status": "OPEN", "demand_profile": "urban_high", "demand_multiplier": 1.0,
        "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
        "inventory": {"DIESEL": diesel, "PETROL": 9000, "OCTANE": 5000},
    }]
    snap.routes = [{
        "id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur",
        "destination_station_id": "station-mirpur", "transit_ticks": 2,
        "max_shipment": 7000, "status": "AVAILABLE",
    }]
    snap.supply_arrivals = []
    snap.events = []
    snap.allocations = []
    snap.demand_history = {
        "station-mirpur": [
            {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": t,
             "sim_time": snap.sim_time, "demand_liters": d, "served_liters": d, "unmet_liters": 0.0}
            for t, d in enumerate(demand)
        ]
    }
    return snap


def test_pipeline_persists_everything() -> None:
    fresh_db()
    pipeline.reset_pipeline_state()
    # Rising demand + low stock → forecast, spike alert, and an LP recommendation.
    demand = [80 + 2 * t for t in range(30)]
    demand[-1] = 400.0  # spike
    snap = _snapshot(tick=30, diesel=800.0, demand=demand)

    pipeline.run_pipeline(snap)
    with db.session_scope() as session:
        forecasts = session.query(Forecast).all()
        risks = session.query(RiskAssessment).all()
        alerts = session.query(Alert).all()
        recs = session.query(Recommendation).all()
        items = session.query(RecommendationItem).all()

    check("forecasts persisted (3 fuels? no — 1 station×fuel with history)", len(forecasts) == 1,
          str(len(forecasts)))
    check("risk assessments persisted", len(risks) == 1)
    check("risk has severity + probability", 0 <= risks[0].stockout_probability <= 1 and risks[0].severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
    check("spike alert raised", any(a.type == "anomaly" and "spike" in a.message.lower() for a in alerts))
    check("recommendation persisted (PROPOSED)", recs and recs[0].status == "PROPOSED")
    check("recommendation has policy", recs[0].policy in {"optimizer", "heuristic"})
    check("risk_before ≥ risk_after", recs[0].risk_before >= recs[0].risk_after - 0.05,
          f"{recs[0].risk_before} → {recs[0].risk_after}")
    check("recommendation items persisted", len(items) >= 1)
    check("item within route max_shipment", all(i.quantity <= 7000 for i in items))
    check("explanation present", bool(recs[0].explanation.get("text")))
    check("explanation source recorded", recs[0].explanation.get("source") in {"template", "llm"})


def test_pipeline_debounces_same_tick() -> None:
    fresh_db()
    pipeline.reset_pipeline_state()
    snap = _snapshot(tick=40, diesel=500.0, demand=[100.0] * 30)
    pipeline.run_pipeline(snap)
    with db.session_scope() as session:
        before = session.query(Forecast).count()
    pipeline.run_pipeline(snap)  # same tick again
    with db.session_scope() as session:
        after = session.query(Forecast).count()
    check("same tick runs once (debounce)", before == after, f"{before} vs {after}")


def test_pipeline_dedupes_alerts() -> None:
    fresh_db()
    pipeline.reset_pipeline_state()
    demand = [100.0] * 30 + [400.0]
    snap = _snapshot(tick=50, diesel=500.0, demand=demand)
    pipeline.run_pipeline(snap)
    with db.session_scope() as session:
        first = session.query(Alert).count()
    snap2 = _snapshot(tick=51, diesel=400.0, demand=demand)
    pipeline.run_pipeline(snap2)
    with db.session_scope() as session:
        second = session.query(Alert).count()
    check("duplicate spike within window not re-alerted", second == first, f"{first} vs {second}")


if __name__ == "__main__":
    t0 = time.time()
    test_template_explanation()
    test_spike_rule()
    test_drop_rule()
    test_delay_rule()
    test_pipeline_persists_everything()
    test_pipeline_debounces_same_tick()
    test_pipeline_dedupes_alerts()
    print(f"\n{len(PASS)} checks passed in {time.time() - t0:.1f}s ✅")
