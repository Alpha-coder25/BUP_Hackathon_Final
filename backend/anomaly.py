"""Anomaly detection rules → alerts (TRD §5 Anomaly).

Rules (must-set from PRD F4):
- demand spike: |latest − μ| / σ > 3 over recent history per station×fuel
- inventory drop: station inventory falls faster than forecast draw
- shipment delay: supply arrival actual_tick > planned_tick (or DELAYED status)

All alerts land in the `alerts` table; never raise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

SPIKE_Z = 3.0
RECENT_WINDOW = 24        # ticks excluded from the baseline (the "current" zone)
BASELINE_WINDOW = 72      # ticks of prior history used as the μ/σ baseline
DROP_RATIO = 0.4          # actual drop > 40% of expected draw → suspicious
DELAY_BUFFER_TICKS = 1    # arrival late by > 1 tick → delay alert


@dataclass
class AnomalyAlert:
    type: str                 # anomaly | disruption | shortage | system
    severity: str             # LOW | MEDIUM | HIGH | CRITICAL
    station_id: str | None
    fuel_type: str | None
    message: str
    created_tick: int


def demand_spike(history_liters: list[float], latest: float, z: float = SPIKE_Z) -> bool:
    """|latest − μ|/σ > 3, where μ/σ come from the baseline BEFORE the recent
    window (not including the latest point).

    Testing against a pre-recent baseline catches both short impulses and
    sustained level shifts (a 12-tick demand_spike event would otherwise pull
    the window's μ/σ toward the spike and hide itself). |abs| also flags a
    demand collapse-to-zero, which is equally anomalous.
    """
    if len(history_liters) < RECENT_WINDOW + 5:
        return False  # not enough history to establish a baseline
    baseline = [v for v in history_liters[:-RECENT_WINDOW] if v is not None]
    baseline = baseline[-BASELINE_WINDOW:]
    if len(baseline) < 5:
        return False
    mu = float(np.mean(baseline))
    sigma = float(np.std(baseline)) or 1.0
    return abs(latest - mu) / sigma > z


def inventory_drop(
    inventory_before: float, inventory_after: float, expected_draw: float
) -> bool:
    """Actual drop much larger than the expected demand draw."""
    if expected_draw <= 0:
        return False
    actual_drop = inventory_before - inventory_after
    return actual_drop > expected_draw * (1 + DROP_RATIO)


def shipment_delay(arrival: dict, current_tick: int) -> bool:
    """Arrival late by more than the buffer, or simulator marked it DELAYED."""
    if arrival.get("status") == "DELAYED":
        return True
    planned = arrival.get("planned_tick")
    actual = arrival.get("actual_tick")
    if planned is None or actual is not None:
        return False  # arrived on record, or nothing planned
    return current_tick - planned > DELAY_BUFFER_TICKS


def evaluate(
    *,
    tick: int,
    demand_history: dict[tuple[str, str], list[float]],
    stations: list[dict],
    station_inventory_before: dict[tuple[str, str], float],
    station_inventory_now: dict[tuple[str, str], float],
    expected_draw: dict[tuple[str, str], float],
    supply_arrivals: list[dict],
) -> list[AnomalyAlert]:
    """Run all rules; return alerts (not yet persisted)."""
    alerts: list[AnomalyAlert] = []

    for (station_id, fuel), history in demand_history.items():
        if not history:
            continue
        latest = history[-1]
        if demand_spike(history, latest):
            alerts.append(
                AnomalyAlert(
                    type="anomaly",
                    severity="HIGH",
                    station_id=station_id,
                    fuel_type=fuel,
                    message=f"Demand spike at {station_id} {fuel}: {latest:.0f} L vs recent μ (z > {SPIKE_Z:g})",
                    created_tick=tick,
                )
            )

    for station in stations:
        for fuel in (station.get("inventory") or {}):
            key = (station["id"], fuel)
            before = station_inventory_before.get(key)
            now = station_inventory_now.get(key)
            draw = expected_draw.get(key)
            if before is None or now is None or draw is None:
                continue
            if inventory_drop(before, now, draw):
                alerts.append(
                    AnomalyAlert(
                        type="anomaly",
                        severity="MEDIUM",
                        station_id=station["id"],
                        fuel_type=fuel,
                        message=(
                            f"Inventory drop at {station['id']} {fuel}: "
                            f"{before:.0f} → {now:.0f} L, expected draw ≈ {draw:.0f} L"
                        ),
                        created_tick=tick,
                    )
                )

    for arrival in supply_arrivals:
        if shipment_delay(arrival, tick):
            alerts.append(
                AnomalyAlert(
                    type="disruption",
                    severity="MEDIUM",
                    station_id=None,
                    fuel_type=arrival.get("fuel_type"),
                    message=(
                        f"Shipment delay: {arrival.get('id')} to {arrival.get('depot_id')} "
                        f"planned tick {arrival.get('planned_tick')} not arrived"
                    ),
                    created_tick=tick,
                )
            )

    return alerts
