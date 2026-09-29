"""SQLAlchemy models for every table in `erd.md` (physical PostgreSQL names).

Groups mirror the ERD: World mirror, Intelligence, Decisions, Operations.
Types are portable (JSONB on PostgreSQL, JSON on SQLite test runs).
Tick-keyed tables are append-only per `DOCS/ERD.md`; `allocations.idempotency_key`
is unique and never reused, matching the simulator's rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, JSONVariant

# SQLite test runs need INTEGER PKs for autoincrement rowid aliasing.
BigInt = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# World mirror (from the simulator)
# ---------------------------------------------------------------------------


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    demand_factor: Mapped[float] = mapped_column(Float, default=1.0)


class Depot(Base):
    __tablename__ = "depots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | CONSTRAINED
    dispatch_capacity_per_tick: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # per fuel


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    name: Mapped[str] = mapped_column(String)
    demand_profile: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | OUTAGE
    demand_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    capacity: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # per fuel


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    destination_station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    transit_ticks: Mapped[int] = mapped_column(Integer, default=0)
    max_shipment: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="AVAILABLE")  # AVAILABLE | DISRUPTED


class DepotInventorySnapshot(Base):
    """Append-only per tick (ERD: world snapshots)."""

    __tablename__ = "depot_inventory_snapshots"
    __table_args__ = (UniqueConstraint("depot_id", "tick", "fuel_type", name="uq_depot_snap"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    tick: Mapped[int] = mapped_column(Integer, index=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fuel_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)


class StationInventorySnapshot(Base):
    """Append-only per tick."""

    __tablename__ = "station_inventory_snapshots"
    __table_args__ = (UniqueConstraint("station_id", "tick", "fuel_type", name="uq_station_snap"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    tick: Mapped[int] = mapped_column(Integer, index=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fuel_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)


class DemandObservation(Base):
    """Append-only per tick; 12 rows/tick in the shipped world (4 stations × 3 fuels)."""

    __tablename__ = "demand_observations"
    __table_args__ = (UniqueConstraint("station_id", "fuel_type", "tick", name="uq_demand_obs"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    fuel_type: Mapped[str] = mapped_column(String)
    tick: Mapped[int] = mapped_column(Integer, index=True)
    demand_liters: Mapped[float] = mapped_column(Float)
    served_liters: Mapped[float] = mapped_column(Float, default=0.0)
    unmet_liters: Mapped[float] = mapped_column(Float, default=0.0)


class SupplyArrival(Base):
    __tablename__ = "supply_arrivals"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # simulator id (supply-001)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    fuel_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    planned_tick: Mapped[int] = mapped_column(Integer)
    actual_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="SCHEDULED")  # SCHEDULED | DELAYED | ARRIVED


class SimEvent(Base):
    __tablename__ = "sim_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # simulator event id
    type: Mapped[str] = mapped_column(String)  # demand_spike | route_disruption | ...
    start_tick: Mapped[int] = mapped_column(Integer)
    end_tick: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="SCHEDULED")  # SCHEDULED | ACTIVE | RESOLVED
    parameters: Mapped[dict] = mapped_column(JSONVariant, default=dict)


# ---------------------------------------------------------------------------
# Intelligence
# ---------------------------------------------------------------------------


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # forecast | anomaly | planner
    version: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    backtest_mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    fuel_type: Mapped[str] = mapped_column(String)
    generated_at_tick: Mapped[int] = mapped_column(Integer)
    target_tick: Mapped[int] = mapped_column(Integer, index=True)
    predicted_liters: Mapped[float] = mapped_column(Float)
    lower_bound: Mapped[float] = mapped_column(Float)
    upper_bound: Mapped[float] = mapped_column(Float)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    fuel_type: Mapped[str] = mapped_column(String)
    tick: Mapped[int] = mapped_column(Integer, index=True)
    hours_to_stockout: Mapped[float | None] = mapped_column(Float, nullable=True)
    stockout_probability: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String)  # LOW | MEDIUM | HIGH | CRITICAL
    confidence: Mapped[float] = mapped_column(Float)
    signals: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    risk_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("risk_assessments.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String)  # shortage | anomaly | disruption | system
    severity: Mapped[str] = mapped_column(String)
    station_id: Mapped[str | None] = mapped_column(ForeignKey("stations.id"), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | ACKED | RESOLVED
    created_tick: Mapped[int] = mapped_column(Integer)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    risk_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("risk_assessments.id"), nullable=True
    )
    policy: Mapped[str] = mapped_column(String)  # heuristic | optimizer | fallback
    tick: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String, default="PROPOSED")  # PROPOSED | APPROVED | REJECTED | EXPIRED
    confidence: Mapped[float] = mapped_column(Float)
    risk_before: Mapped[float] = mapped_column(Float)
    risk_after: Mapped[float] = mapped_column(Float)
    explanation: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    alternatives: Mapped[list] = mapped_column(JSONVariant, default=list)
    expires_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    fuel_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[str] = mapped_column(String, default="viewer")  # viewer | operator | admin
    password_hash: Mapped[str] = mapped_column(String, default="")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    action: Mapped[str] = mapped_column(String)  # APPROVED | REJECTED | MODIFIED | AUTO
    note: Mapped[str] = mapped_column(String, default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Allocation(Base):
    """Mirror of the simulator ledger; `idempotency_key` is unique and never reused."""

    __tablename__ = "allocations"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    sim_allocation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    recommendation_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_items.id"), nullable=True
    )
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"))
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id"))
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    fuel_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | IN_TRANSIT | ARRIVED | FAILED | CANCELLED
    created_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departure_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_arrival_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_arrival_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


class ServiceHealthCheck(Base):
    __tablename__ = "service_health_checks"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String)  # backend | db | simulator | forecaster | planner
    status: Mapped[str] = mapped_column(String)  # HEALTHY | DEGRADED | DOWN
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FallbackEvent(Base):
    __tablename__ = "fallback_events"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    fallback_policy: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy: Mapped[str] = mapped_column(String)
    seed: Mapped[int] = mapped_column(Integer)
    scenario: Mapped[str] = mapped_column(String)
    ticks: Mapped[int] = mapped_column(Integer)
    service_level: Mapped[float] = mapped_column(Float)
    unmet_liters: Mapped[float] = mapped_column(Float)
    allocation_failures: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = [
    "Alert",
    "Allocation",
    "AuditLog",
    "BenchmarkRun",
    "Decision",
    "DemandObservation",
    "Depot",
    "DepotInventorySnapshot",
    "FallbackEvent",
    "Forecast",
    "ModelVersion",
    "Operator",
    "Recommendation",
    "RecommendationItem",
    "Region",
    "RiskAssessment",
    "Route",
    "ServiceHealthCheck",
    "SimEvent",
    "Station",
    "StationInventorySnapshot",
    "SupplyArrival",
]
