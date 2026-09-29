"""Decision-path tests — approve (idempotency, rollback, 409 mapping), reject, history.

Run:  .venv/bin/python backend/tests/test_decisions.py
Uses the mock simulator over HTTP (same harness as test_integration_mock.py)
and a fresh SQLite DB per test.
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

from backend import db, decisions  # noqa: E402
from backend.models import (  # noqa: E402
    Allocation,
    AuditLog,
    Decision,
    Recommendation,
    RecommendationItem,
)
from backend.simulator_client import SimulatorClient  # noqa: E402

PASS: list[str] = []
PORT = 8766
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


def fresh_db() -> None:
    for attr in ("_engine", "_SessionLocal"):
        setattr(db, attr, None)
    db.DB_URL = f"sqlite:///tmp-decisions-{uuid.uuid4().hex}.db"
    db.init_db()
    # Reset the mock's world + idempotency ledger: keys never free (guide §5.4),
    # and fresh test DBs restart rec ids at 1 — without a reset, key collisions
    # across tests would masquerade as IDEMPOTENCY_KEY_MISMATCH.
    httpx.post(f"{BASE}/__mock/reset")


def seed_recommendation(items: list[dict], expires_offset: int | None = 50) -> int:
    with db.session_scope() as session:
        rec = Recommendation(
            policy="optimizer", tick=0, status="PROPOSED",
            confidence=0.9, risk_before=0.8, risk_after=0.2,
            explanation={"text": "t", "source": "template"},
            alternatives=[], expires_tick=expires_offset,
        )
        session.add(rec)
        session.flush()
        for it in items:
            session.add(RecommendationItem(
                recommendation_id=rec.id, **it
            ))
        return rec.id


GOOD_ITEMS = [
    {"depot_id": "depot-gazipur", "station_id": "station-mirpur",
     "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 3000.0},
]
BIG_ITEMS = [
    {"depot_id": "depot-gazipur", "station_id": "station-mirpur",
     "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 99999.0},
]

proc = subprocess.Popen(
    [sys.executable, "-m", "mock_simulator.server"],
    cwd=ROOT, env={**__import__("os").environ, "PORT": str(PORT), "SIMULATION_SPEED": "4"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    wait_port(PORT)
    client = SimulatorClient(base_url=BASE)
    decisions.get_client = lambda: client  # route decisions at the mock

    # ---------------------------------------------------------- happy path

    def test_approve_happy_path() -> None:
        fresh_db()
        rec_id = seed_recommendation(GOOD_ITEMS)
        out = decisions.approve_recommendation(rec_id, note="go")
        check("approve returns APPROVED", out["status"] == "APPROVED")
        check("one allocation mirrored", len(out["allocations"]) == 1)
        key = out["allocations"][0]["idempotency_key"]
        check("idempotency key = {rec}:{seq}", key == f"{rec_id}:1", key)
        with db.session_scope() as session:
            rec = session.get(Recommendation, rec_id)
            check("rec APPROVED", rec.status == "APPROVED")
            check("decision row written", session.query(Decision).filter_by(recommendation_id=rec_id).count() == 1)
            check("audit row written", session.query(AuditLog).filter_by(entity_id=str(rec_id)).count() >= 1)
            alloc = session.query(Allocation).filter_by(idempotency_key=key).one()
            check("allocation PENDING mirror", alloc.status == "PENDING" and alloc.sim_allocation_id is not None)
        # Idempotency: approving a second time is INVALID_STATE (already approved)
        try:
            decisions.approve_recommendation(rec_id)
            check("double approve blocked", False)
        except decisions.DecisionError as e:
            check("double approve blocked", e.code == "INVALID_STATE")

    # ------------------------------------------------------- rollback path

    def test_approve_rollback_on_409() -> None:
        fresh_db()
        rec_id = seed_recommendation(BIG_ITEMS)  # exceeds route.max_shipment
        try:
            decisions.approve_recommendation(rec_id)
            check("oversized item → SUBMISSION_FAILED", False)
        except decisions.DecisionError as e:
            check("oversized item → SUBMISSION_FAILED", e.code == "SUBMISSION_FAILED")
            check("409 mapped to operator message", "max shipment" in e.detail["failures"][0]["message"].lower())
        with db.session_scope() as session:
            rec = session.get(Recommendation, rec_id)
            check("rec still PROPOSED after failure", rec.status == "PROPOSED")
            check("no decision row on failure",
                  session.query(Decision).filter_by(recommendation_id=rec_id).count() == 0)
            check("failed attempt audited",
                  session.query(AuditLog).filter_by(action="recommendation.approve_failed").count() == 1)

    # -------------------------------------------------------- partial fail

    def test_partial_rollback() -> None:
        fresh_db()
        # Item 1 fits, item 2 exceeds route capacity → item 1 must be cancelled
        rec_id = seed_recommendation([
            GOOD_ITEMS[0],
            {"depot_id": "depot-gazipur", "station_id": "station-mirpur",
             "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 99999.0},
        ])
        try:
            decisions.approve_recommendation(rec_id)
            check("mixed batch fails", False)
        except decisions.DecisionError as e:
            check("mixed batch fails", e.code == "SUBMISSION_FAILED")
            check("first item rolled back", e.detail.get("rolled_back", 0) is not None)
        with db.session_scope() as session:
            statuses = {
                a.idempotency_key: a.status
                for a in session.query(Allocation).filter(
                    Allocation.idempotency_key.like(f"{rec_id}:%")
                ).all()
            }
            check("created allocation cancelled", statuses.get(f"{rec_id}:1") == "CANCELLED", str(statuses))

    # ----------------------------------------------------------- expiry etc

    def test_gates() -> None:
        fresh_db()
        rec_id = seed_recommendation(GOOD_ITEMS, expires_offset=-5)  # already expired vs tick
        try:
            decisions.approve_recommendation(rec_id)
            check("expired rec rejected", False)
        except decisions.DecisionError as e:
            check("expired rec rejected", e.code in ("EXPIRED", "STALE_WORLD"))
        try:
            decisions.approve_recommendation(99999)
            check("unknown rec → NOT_FOUND", False)
        except decisions.DecisionError as e:
            check("unknown rec → NOT_FOUND", e.code == "NOT_FOUND")

    def test_reject_and_history() -> None:
        fresh_db()
        rec_id = seed_recommendation(GOOD_ITEMS)
        out = decisions.reject_recommendation(rec_id, note="too expensive")
        check("reject → REJECTED", out["status"] == "REJECTED")
        with db.session_scope() as session:
            check("rec EXPIRED after reject", session.get(Recommendation, rec_id).status == "EXPIRED")
        h = decisions.history(recommendation_id=rec_id)
        check("history shows decision", len(h["decisions"]) == 1 and h["decisions"][0]["action"] == "REJECTED")

    test_approve_happy_path()
    test_approve_rollback_on_409()
    test_partial_rollback()
    test_gates()
    test_reject_and_history()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print(f"\n{len(PASS)} checks passed ✅")
