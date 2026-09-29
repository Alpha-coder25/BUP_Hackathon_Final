"""Decision write path — `DOCS/BackendImplementation.md` §6, `DOCS/ApplicationFlow.md`.

Approve:
  1. Gate on world freshness (stale data → no safe write) + rec state/expiry.
  2. Re-check per-item constraints fresh from the simulator world.
  3. POST /v1/allocations per item, idempotency key {rec_id}:{seq}.
  4. Any failure → cancel already-created PENDING shipments, NO decision row,
     recommendation stays PROPOSED, actionable error to the operator.
  5. Full success → decision (APPROVED) + audit_log + allocation mirrors.

Reject: decision (REJECTED) + recommendation EXPIRED; alert stays OPEN.

409 codes map to operator-actionable messages (simulator guide §9).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import (
    Allocation,
    AuditLog,
    Decision,
    Recommendation,
    RecommendationItem,
    Operator,
)
from .simulator_client import SimulatorAllocationError, SimulatorClient, get_client

log = logging.getLogger(__name__)

DEFAULT_OPERATOR_NAME = "ops-console"

# Operator-actionable messages per simulator error code (guide §9)
USER_MESSAGES: dict[str, str] = {
    "ROUTE_CAPACITY_EXCEEDED": "Quantity exceeds this route's max shipment — the plan should be split into smaller shipments.",
    "DISPATCH_CAPACITY_EXCEEDED": "Depot dispatch capacity is used up this tick — wait for the next tick and retry.",
    "INSUFFICIENT_INVENTORY": "Depot no longer has enough fuel — wait for the next supply arrival or pick another depot.",
    "DESTINATION_CAPACITY_EXCEEDED": "The station tank would overflow — wait for demand to consume stock.",
    "ROUTE_DISRUPTED": "This route was disrupted since the plan was made — a new recovery plan is needed.",
    "ROUTE_MISMATCH": "Route does not connect that depot–station pair — the plan is stale, wait for a new one.",
    "STATION_CLOSED": "Station is in outage — shipments are blocked until it reopens.",
    "DEPOT_CLOSED": "Depot is closed — pick another depot.",
    "NOT_FOUND": "Depot, station or route no longer exists — the plan is stale.",
    "IDEMPOTENCY_KEY_MISMATCH": "Internal keying conflict — contact ops.",
}


class DecisionError(Exception):
    """User-facing decision failure; `code` maps to an HTTP status."""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code  # NOT_FOUND | INVALID_STATE | EXPIRED | STALE_WORLD | SUBMISSION_FAILED
        self.message = message
        self.detail = detail or {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_operator(session: Session, name: str) -> Operator:
    op = session.execute(select(Operator).where(Operator.name == name)).scalar_one_or_none()
    if op is None:
        op = Operator(name=name, role="operator")
        session.add(op)
        session.flush()
    return op


def _require_fresh_world(client: SimulatorClient) -> int:
    """No fresh world = no safe write (ScreenFlow navigation rule)."""
    try:
        data, stale = client.instance()
    except Exception as exc:  # noqa: BLE001
        raise DecisionError("STALE_WORLD", "Simulator unreachable — approvals are disabled until it recovers.", {"detail": str(exc)[:200]})
    if stale:
        raise DecisionError("STALE_WORLD", "Simulator data is stale — approvals are disabled until fresh data arrives.")
    return int(data.get("tick", 0))


def _mirror_allocation(session: Session, item: RecommendationItem, key: str, payload: dict) -> Allocation:
    alloc = session.execute(
        select(Allocation).where(Allocation.idempotency_key == key)
    ).scalar_one_or_none()
    if alloc is None:
        alloc = Allocation(
            idempotency_key=key,
            recommendation_item_id=item.id,
            depot_id=item.depot_id,
            station_id=item.station_id,
            route_id=item.route_id,
            fuel_type=item.fuel_type,
            quantity=item.quantity,
        )
        session.add(alloc)
    alloc.sim_allocation_id = payload.get("id")
    alloc.status = payload.get("status", "PENDING")
    alloc.created_tick = payload.get("created_tick")
    alloc.departure_tick = payload.get("departure_tick")
    alloc.expected_arrival_tick = payload.get("expected_arrival_tick")
    alloc.failure_reason = payload.get("failure_reason")
    return alloc


def _cancel_pending(client: SimulatorClient, submitted: list[dict]) -> None:
    """Best-effort rollback of PENDING shipments after a partial failure."""
    for entry in submitted:
        try:
            client.cancel_allocation(entry["sim_allocation_id"])
            entry["status"] = "CANCELLED"
        except SimulatorAllocationError as exc:
            if exc.code == "CANNOT_CANCEL":
                entry["status"] = "IN_TRANSIT"  # already moving; it will arrive
            log.warning("rollback cancel failed for %s: %s", entry.get("idempotency_key"), exc.code)
        except Exception as exc:  # noqa: BLE001
            log.warning("rollback cancel errored for %s: %s", entry.get("idempotency_key"), exc)


def approve_recommendation(
    recommendation_id: int, note: str = "", operator_name: str | None = None
) -> dict:
    """Execute the full approve path. Raises DecisionError on any failure."""
    client = get_client()
    tick = _require_fresh_world(client)

    failure: DecisionError | None = None
    submitted: list[dict] = []
    rec_id: int | None = None
    n_items = 0

    with session_scope() as session:
        rec = session.get(Recommendation, recommendation_id)
        if rec is None:
            raise DecisionError("NOT_FOUND", f"Recommendation {recommendation_id} not found.")
        if rec.status != "PROPOSED":
            raise DecisionError("INVALID_STATE", f"Recommendation is {rec.status}, not PROPOSED.")
        if rec.expires_tick is not None and rec.expires_tick < tick:
            rec.status = "EXPIRED"
            raise DecisionError("EXPIRED", "Recommendation expired before approval — a newer plan is available.")

        items = session.execute(
            select(RecommendationItem)
            .where(RecommendationItem.recommendation_id == rec.id)
            .order_by(RecommendationItem.id)
        ).scalars().all()
        if not items:
            raise DecisionError("INVALID_STATE", "Recommendation has no items.")
        rec_id, n_items = rec.id, len(items)

        failures: list[dict] = []
        try:
            for seq, item in enumerate(items, start=1):
                base_key = client.make_idempotency_key(str(rec.id), seq)
                try:
                    # §5.4: keys are never freed. If a previous attempt burned
                    # this key and its allocation ended CANCELLED/FAILED,
                    # replaying it returns the dead allocation — resubmit under
                    # a fresh key so the shipment actually happens.
                    key = base_key
                    payload = None
                    for attempt in range(3):
                        probe_key = key if attempt == 0 else f"{key}:r{attempt + 1}"
                        payload = client.create_allocation(
                            idempotency_key=probe_key,
                            source_depot_id=item.depot_id,
                            destination_station_id=item.station_id,
                            route_id=item.route_id,
                            fuel_type=item.fuel_type,
                            quantity=item.quantity,
                        )
                        key = probe_key
                        if payload.get("status") not in ("CANCELLED", "FAILED"):
                            break
                    alloc = _mirror_allocation(session, item, key, payload)
                    submitted.append({
                        "idempotency_key": key,
                        "sim_allocation_id": payload.get("id"),
                        "status": alloc.status,
                        "depot_id": item.depot_id,
                        "station_id": item.station_id,
                        "fuel_type": item.fuel_type,
                        "quantity": item.quantity,
                    })
                except SimulatorAllocationError as exc:
                    failures.append({
                        "depot_id": item.depot_id,
                        "station_id": item.station_id,
                        "fuel_type": item.fuel_type,
                        "quantity": item.quantity,
                        "code": exc.code,
                        "message": USER_MESSAGES.get(exc.code, exc.message),
                    })
                    break  # first failure aborts the batch (rollback below)
        except Exception as exc:  # noqa: BLE001 — transport-level failure
            failures.append({"code": "TRANSPORT", "message": f"Simulator submission failed: {exc}"})

        if failures:
            # Roll back created PENDING shipments, mirror their final statuses,
            # audit the attempt — all committed BEFORE the error propagates
            # (raising inside session_scope would roll the audit row back).
            _cancel_pending(client, submitted)
            for entry in submitted:
                alloc = session.execute(
                    select(Allocation).where(Allocation.idempotency_key == entry["idempotency_key"])
                ).scalar_one_or_none()
                if alloc is not None:
                    alloc.status = entry["status"]
            operator = _ensure_operator(session, operator_name or DEFAULT_OPERATOR_NAME)
            session.add(AuditLog(
                operator_id=operator.id,
                action="recommendation.approve_failed",
                entity_type="recommendation",
                entity_id=str(rec.id),
                payload={"failures": failures, "rolled_back": len(submitted), "tick": tick},
            ))
            failure = DecisionError(
                "SUBMISSION_FAILED",
                "Allocation rejected by the simulator — created shipments were rolled back.",
                {"failures": failures, "rolled_back": submitted},
            )
        else:
            operator = _ensure_operator(session, operator_name or DEFAULT_OPERATOR_NAME)
            rec.status = "APPROVED"
            session.add(Decision(
                recommendation_id=rec.id, operator_id=operator.id, action="APPROVED", note=note or ""
            ))
            session.add(AuditLog(
                operator_id=operator.id,
                action="recommendation.approved",
                entity_type="recommendation",
                entity_id=str(rec.id),
                payload={"items": len(items), "tick": tick},
            ))

    if failure is not None:
        raise failure

    try:
        from .events import publish

        publish("recommendation.decided", {"recommendation_id": rec_id, "action": "APPROVED", "tick": tick})
    except Exception:  # noqa: BLE001
        pass
    return {
        "recommendation_id": rec_id,
        "status": "APPROVED",
        "decided_at": _now().isoformat(),
        "allocations": submitted,
    }


def reject_recommendation(
    recommendation_id: int, note: str = "", operator_name: str | None = None
) -> dict:
    """Record the rejection; recommendation EXPIRED; alert stays OPEN."""
    with session_scope() as session:
        rec = session.get(Recommendation, recommendation_id)
        if rec is None:
            raise DecisionError("NOT_FOUND", f"Recommendation {recommendation_id} not found.")
        if rec.status != "PROPOSED":
            raise DecisionError("INVALID_STATE", f"Recommendation is {rec.status}, not PROPOSED.")
        operator = _ensure_operator(session, operator_name or DEFAULT_OPERATOR_NAME)
        rec.status = "EXPIRED"
        session.add(Decision(
            recommendation_id=rec.id, operator_id=operator.id, action="REJECTED", note=note or ""
        ))
        session.add(AuditLog(
            operator_id=operator.id,
            action="recommendation.rejected",
            entity_type="recommendation",
            entity_id=str(rec.id),
            payload={"note": note or ""},
        ))
        rec_id = rec.id
    try:
        from .events import publish

        publish("recommendation.decided", {"recommendation_id": rec_id, "action": "REJECTED"})
    except Exception:  # noqa: BLE001
        pass
    return {"recommendation_id": rec_id, "status": "REJECTED", "decided_at": _now().isoformat()}


def history(limit: int = 100, recommendation_id: int | None = None,
            station_id: str | None = None, fuel_type: str | None = None) -> dict:
    """Past decisions + allocations with statuses and failure reasons."""
    from .models import Route, Station  # local to avoid cycles

    limit = max(1, min(limit, 500))
    with session_scope() as session:
        dq = select(
            Decision.id, Decision.recommendation_id, Decision.action,
            Decision.note, Decision.decided_at, Operator.name.label("operator"),
        ).join(Operator, Operator.id == Decision.operator_id)
        if recommendation_id is not None:
            dq = dq.where(Decision.recommendation_id == recommendation_id)
        decisions = [
            dict(r._mapping) for r in session.execute(dq.order_by(Decision.id.desc()).limit(limit))
        ]

        aq = select(
            Allocation.id, Allocation.idempotency_key, Allocation.sim_allocation_id,
            Allocation.depot_id, Allocation.station_id, Allocation.route_id,
            Allocation.fuel_type, Allocation.quantity, Allocation.status,
            Allocation.created_tick, Allocation.actual_arrival_tick, Allocation.failure_reason,
            RecommendationItem.recommendation_id,
        ).outerjoin(RecommendationItem, RecommendationItem.id == Allocation.recommendation_item_id)
        if recommendation_id is not None:
            aq = aq.where(RecommendationItem.recommendation_id == recommendation_id)
        if station_id:
            aq = aq.where(Allocation.station_id == station_id)
        if fuel_type:
            aq = aq.where(Allocation.fuel_type == fuel_type)
        allocations = [
            dict(r._mapping) for r in session.execute(aq.order_by(Allocation.id.desc()).limit(limit))
        ]
    return {"decisions": decisions, "allocations": allocations}
