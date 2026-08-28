"""Forward quantile price-path projection (§1 step 6 — real data path).

The kittenCN temporal port needs multi-hour training (no pre-trained weights),
but the repo's *existing* trained long-term model already emits q10/q50/q90
horizon-end return quantiles per task (``model_readings[task]`` has ``q10``,
``q50``, ``q90``, ``horizon_days``, ``prediction_interval_width``).  This
helper turns those quantiles into a forward predicted price path + q10–q90
band, anchored at ``latest_close``, so the predicted-vs-actual chart shows a
REAL forward fan instead of "unavailable" — without waiting for the kittenCN
port.

Honest caveats (encoded in the ``model`` label):
- The model gives a single horizon-end quantile fan, **not** a daily temporal
  trajectory; the path is the horizon-end return linearly interpolated to a
  daily axis for plotting.  This is a projection, not a kittenCN path model.
- ``mean_abs_error_pct`` is the model's *realized* return-prediction error for
  this asset (from ``walk_forward_daily.mean_abs_error``), so the chart's
  error readout is grounded in this stock's archived accuracy, not a guess.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def _as_date(as_of: Any):
    if hasattr(as_of, "date"):
        return as_of.date()
    if isinstance(as_of, str):
        return datetime.fromisoformat(as_of[:10]).date()
    return as_of


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_price_path_projection(
    model_readings: Mapping[str, Mapping[str, Any]] | None,
    latest_close: float | None,
    as_of: Any,
    realized_mae: float | None = None,
    task: str = "excess_return_240d",
    n_points: int = 40,
) -> dict:
    """Project a forward price path + q10–q90 band from the model's quantiles.

    Degrades to ``status="unavailable"`` (with a concrete reason) when the
    model reading, quantiles, or latest close are missing — never fabricates.
    """
    readings = model_readings or {}
    reading = readings.get(task)
    if not isinstance(reading, Mapping):
        return {
            "status": "unavailable",
            "reason": "no_model_reading",
            "model": None,
            "horizon_days": None,
            "mean_abs_error_pct": None,
            "generated_at": None,
            "points": [],
        }
    q10 = _num(reading.get("q10"))
    q50 = _num(reading.get("q50"))
    q90 = _num(reading.get("q90"))
    horizon = _num(reading.get("horizon_days")) or 240
    if q10 is None or q50 is None or q90 is None:
        return {
            "status": "unavailable",
            "reason": "quantiles_missing",
            "model": None,
            "horizon_days": horizon,
            "mean_abs_error_pct": realized_mae,
            "generated_at": None,
            "points": [],
        }
    if latest_close is None or not isinstance(latest_close, (int, float)) or isinstance(latest_close, bool):
        return {
            "status": "unavailable",
            "reason": "no_latest_close",
            "model": None,
            "horizon_days": horizon,
            "mean_abs_error_pct": realized_mae,
            "generated_at": None,
            "points": [],
        }

    base = float(latest_close)
    as_of_date = _as_date(as_of)
    span_days = max(1, int(horizon))
    step = max(1, span_days // max(1, n_points - 1))

    points: list[dict] = []
    i = 0
    while i <= span_days:
        t = i / span_days if span_days else 0.0
        date_obj = as_of_date + timedelta(days=i)
        points.append(
            {
                "date": date_obj.isoformat() if hasattr(date_obj, "isoformat") else str(date_obj),
                "actual": round(base, 2) if i == 0 else None,
                "predicted": round(base * (1.0 + q50 * t), 2),
                "q10": round(base * (1.0 + q10 * t), 2),
                "q90": round(base * (1.0 + q90 * t), 2),
            }
        )
        i += step
    # Always include the horizon end-point so the fan closes at +horizon.
    end_date = as_of_date + timedelta(days=span_days)
    end_iso = end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date)
    if not points or points[-1]["date"] != end_iso:
        points.append(
            {
                "date": end_iso,
                "actual": None,
                "predicted": round(base * (1.0 + q50), 2),
                "q10": round(base * (1.0 + q10), 2),
                "q90": round(base * (1.0 + q90), 2),
            }
        )

    return {
        "status": "ok",
        "model": f"long-term-{task} (quantile projection, {int(horizon)}d)",
        "horizon_days": int(horizon),
        "mean_abs_error_pct": realized_mae,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "points": points,
    }
