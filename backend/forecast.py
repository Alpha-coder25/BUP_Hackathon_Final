"""Demand forecast + stockout risk per station×fuel.

Contract: `DOCS/TRD.md` §5 (Forecast), `DOCS/BackendImplementation.md` §4.

- Features: hour, day-of-week, lag-1 demand, 6-tick rolling mean.
- Three quantile GBMs (P10/P50/P90) per station×fuel → uncertainty for free.
- hours_to_stockout = (inventory + in-flight + incoming) / P50 per hour.
- stockout_probability via 2000-draw Monte Carlo, σ = (P90−P50)/1.28.
- Fallback: moving average when < MIN_HISTORY_ROWS or bands too wide
  ((P90−P10)/P50 > 0.8). Fallback decisions surface as low confidence —
  callers mark those "Human review requested".
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

log = logging.getLogger(__name__)

MIN_HISTORY_ROWS = 20          # below this → moving-average fallback
WIDE_BAND_RATIO = 0.8          # (P90−P10)/P50 above this → low confidence
QUANTILES = (0.1, 0.5, 0.9)
MONTE_CARLO_DRAWS = 2000
Z_P90 = 1.28                   # P90 z-score under normality
FORECAST_HORIZON_TICKS = 8     # 8 × 15 min = 2 simulated hours ahead
SEVERITY_CUTOFFS = ((0.9, "CRITICAL"), (0.7, "HIGH"), (0.4, "MEDIUM"))  # else LOW
FEATURES = ["hour", "dow", "lag1", "roll6"]


@dataclass
class ForecastPoint:
    """One station×fuel forecast row — maps to `forecasts` + `risk_assessments`
    in `DOCS/ERD.md`."""

    station_id: str
    fuel_type: str
    target_tick: int
    predicted_liters: float
    lower_bound: float        # P10
    upper_bound: float        # P90
    hours_to_stockout: float | None
    stockout_probability: float  # 0..1
    severity: str             # LOW / MEDIUM / HIGH / CRITICAL
    confidence: float         # 0..1
    model_kind: str           # "quantile_gbm" | "moving_average"
    model_version: str = ""
    signals: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def make_features(history: pd.DataFrame) -> pd.DataFrame:
    """history: columns [tick, sim_time, demand_liters] sorted by tick."""
    df = history.sort_values("tick").copy()
    df["hour"] = pd.to_datetime(df["sim_time"]).dt.hour
    df["dow"] = pd.to_datetime(df["sim_time"]).dt.dayofweek
    df["lag1"] = df["demand_liters"].shift(1)
    df["roll6"] = df["demand_liters"].rolling(6).mean()
    return df.dropna(subset=FEATURES + ["demand_liters"])


def next_feature_row(history: pd.DataFrame, sim_time: str) -> dict:
    """Feature vector for the tick being forecast (lag1/roll6 from history tail)."""
    demand = history.sort_values("tick")["demand_liters"]
    ts = pd.Timestamp(sim_time)
    return {
        "hour": ts.hour,
        "dow": ts.dayofweek,
        "lag1": float(demand.iloc[-1]),
        "roll6": float(demand.tail(6).mean()),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def train_quantile_models(history: pd.DataFrame) -> dict[float, GradientBoostingRegressor] | None:
    """Train P10/P50/P90 GBMs. None when history is too thin for a real model."""
    if len(history) < MIN_HISTORY_ROWS:
        return None
    d = make_features(history)
    if len(d) < MIN_HISTORY_ROWS:
        return None
    x, y = d[FEATURES], d["demand_liters"]
    return {
        q: GradientBoostingRegressor(loss="quantile", alpha=q).fit(x, y) for q in QUANTILES
    }


def moving_average(history: pd.DataFrame, n: int = 6) -> float:
    """Fallback prediction when the model is unavailable or too unsure."""
    return float(history.sort_values("tick")["demand_liters"].tail(n).mean())


def predict_quantiles(
    models: dict[float, GradientBoostingRegressor], feature_row: dict
) -> tuple[float, float, float]:
    x = pd.DataFrame([feature_row])[FEATURES]
    p10 = float(models[0.1].predict(x)[0])
    p50 = float(models[0.5].predict(x)[0])
    p90 = float(models[0.9].predict(x)[0])
    # Enforce quantile crossing (GBMs can produce crossed bands on small data).
    return max(p10, 0.0), max(p50, p10), max(p90, p50)


def band_confidence(p10: float, p50: float, p90: float, rows: int) -> float:
    """1.0 = sure, →0 = unsure. Wide bands or thin history down-weight it."""
    band_ratio = (p90 - p10) / max(p50, 1e-6)
    width_score = max(0.0, 1.0 - band_ratio / WIDE_BAND_RATIO)
    data_score = min(1.0, rows / (2 * MIN_HISTORY_ROWS))
    return round(0.7 * width_score + 0.3 * data_score, 3)


def is_low_confidence(p10: float, p50: float, p90: float) -> bool:
    return (p90 - p10) / max(p50, 1e-6) > WIDE_BAND_RATIO


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

def hours_to_stockout(
    inventory_liters: float, incoming_liters: float, p50_per_tick: float, tick_minutes: int = 15
) -> float | None:
    """(inventory + in-flight + incoming) / expected draw. None when demand ~ 0."""
    per_hour = p50_per_tick * (60.0 / tick_minutes)
    if per_hour <= 1e-9:
        return None
    return round((inventory_liters + incoming_liters) / per_hour, 2)


def stockout_probability(
    inventory_liters: float,
    incoming_liters: float,
    p50: float,
    p90: float,
    horizon: int = FORECAST_HORIZON_TICKS,
    draws: int = MONTE_CARLO_DRAWS,
) -> float:
    """P(horizon demand > supply) over `draws` Monte Carlo samples.

    Demand is the sum over `horizon` ticks (CLT): N(horizon·p50, √horizon·σ),
    σ = (p90−p50)/1.28 per tick — a single-tick draw against total inventory
    would read ~0 until the tank is nearly empty.
    """
    sigma_tick = max((p90 - p50) / Z_P90, 1e-6)
    demand = np.random.normal(horizon * p50, math.sqrt(horizon) * sigma_tick, draws)
    supply = inventory_liters + incoming_liters
    return float((demand > supply).mean())


def severity_for(probability: float) -> str:
    for cutoff, name in SEVERITY_CUTOFFS:
        if probability >= cutoff:
            return name
    return "LOW"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def forecast_station_fuel(
    *,
    station_id: str,
    fuel_type: str,
    history: pd.DataFrame,
    inventory_liters: float,
    incoming_liters: float,
    target_tick: int,
    target_sim_time: str,
    tick_minutes: int = 15,
    model_version: str = "",
) -> ForecastPoint:
    """Full forecast + risk for one station×fuel. Never raises: thin data or a
    failing model degrades to the moving-average fallback (marked low confidence)."""
    rows = len(history)
    try:
        models = train_quantile_models(history)
        if models is not None:
            p10, p50, p90 = predict_quantiles(models, next_feature_row(history, target_sim_time))
            model_kind = "quantile_gbm"
            low_conf = is_low_confidence(p10, p50, p90)
        else:
            p10 = p50 = p90 = moving_average(history)
            model_kind = "moving_average"
            low_conf = True
    except Exception as exc:  # noqa: BLE001 — model failure must not stop the pipeline
        log.warning("forecast fallback station=%s fuel=%s: %s", station_id, fuel_type, exc)
        p10 = p50 = p90 = moving_average(history)
        model_kind, low_conf, rows = "moving_average", True, len(history)

    confidence = band_confidence(p10, p50, p90, rows)
    if low_conf:
        confidence = min(confidence, 0.5)  # force "Human review requested" path
    probability = stockout_probability(inventory_liters, incoming_liters, p50, p90)

    return ForecastPoint(
        station_id=station_id,
        fuel_type=fuel_type,
        target_tick=target_tick,
        predicted_liters=round(p50, 2),
        lower_bound=round(p10, 2),
        upper_bound=round(p90, 2),
        hours_to_stockout=hours_to_stockout(inventory_liters, incoming_liters, p50, tick_minutes),
        stockout_probability=round(probability, 4),
        severity=severity_for(probability),
        confidence=confidence,
        model_kind=model_kind,
        model_version=model_version,
        signals={"rows": rows, "low_band_confidence": low_conf, "horizon_ticks": FORECAST_HORIZON_TICKS},
    )
