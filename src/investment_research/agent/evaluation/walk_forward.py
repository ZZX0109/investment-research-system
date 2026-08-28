"""Per-asset walk-forward summary (§1 step 7 / §3 get_model_walkforward_daily).

Computes a daily (per-decision-date) accuracy + error view from the archived
predicted-vs-actual readings (``ModelHistoryPoint``) that the snapshot already
carries.  This is the per-asset complement to the global ``accuracy_surface``
(variant-level rank_ic / p50_mae): here the LLM can cite "for this stock the
model's directional calls were right X of N times, mean abs error Y%".

Pure + dependency-free so it is unit-testable with canned history and so the
snapshot builder can call it without a network or a trained-on-the-fly model.
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Protocol


class _HistoryPoint(Protocol):
    """Structural shape of ``ModelHistoryPoint`` (duck-typed to avoid a hard
    import cycle: this module is imported by the snapshot builder)."""

    decision_date: str
    predicted_return: float
    actual_return: float


def load_model_prediction_history(project_root: object, symbol: str) -> list:
    """§3 row-5 shared loader: read archived OOF/holdout predictions for
    ``symbol`` from the compact parquet artifact + group by decision date
    (mean predicted vs actual).  Used by BOTH the snapshot builder's
    ``walk_forward_daily`` field + the ``get_model_validation_metrics`` tool
    handler (so the LLM can cite per-asset daily accuracy via the tool, not
    just the snapshot).  Returns a list of ``SimpleNamespace(decision_date,
    predicted_return, actual_return)`` — duck-typed to satisfy
    ``summarize_walk_forward``'s ``_HistoryPoint`` Protocol.  Degrades to
    ``[]`` when the artifact / pyarrow is missing or the symbol has no rows
    (never synthesizes numbers)."""
    path = Path(str(project_root)) / "artifacts" / "long_term_training" / "latest.predictions.parquet"
    try:
        import pyarrow.parquet as parquet

        table = parquet.read_table(
            path,
            columns=["split", "symbol", "decision_date", "target", "score"],
        )
    except (ImportError, OSError, ValueError, KeyError):
        return []
    requested = "".join(ch for ch in str(symbol).upper() if ch.isalnum()).zfill(6)
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in table.to_pylist():
        split = str(row.get("split") or "")
        if split not in {"oof", "holdout"}:
            continue
        candidate = "".join(ch for ch in str(row.get("symbol") or "").upper() if ch.isalnum()).zfill(6)
        if candidate != requested:
            continue
        decision_date = str(row.get("decision_date") or "")[:10]
        try:
            predicted = float(row["score"])
            actual = float(row["target"])
        except (KeyError, TypeError, ValueError):
            continue
        if not decision_date or not math.isfinite(predicted) or not math.isfinite(actual):
            continue
        grouped.setdefault(decision_date, []).append((predicted, actual))
    return [
        SimpleNamespace(
            decision_date=date,
            predicted_return=statistics.fmean(item[0] for item in values),
            actual_return=statistics.fmean(item[1] for item in values),
        )
        for date, values in sorted(grouped.items())
    ]


def summarize_walk_forward(history: Iterable[_HistoryPoint]) -> dict:
    """Summarize a per-asset predicted-vs-actual walk-forward record.

    Returns a dict with ``status``, ``decision_count``, ``directional_accuracy``
    (fraction of dates where the predicted *sign* matched the actual sign),
    ``mean_abs_error``, ``mean_signed_error`` (bias: positive = over-predict),
    and ``dates`` — one entry per decision date with predicted/actual/correct/
    abs_error, so the LLM + the predicted-vs-actual chart can show the daily
    detail.  Degrades to ``status="unavailable"`` when there is no history
    (never synthesizes numbers).
    """
    points = sorted(
        (p for p in history if p is not None),
        key=lambda item: getattr(item, "decision_date", "") or "",
    )
    points = [p for p in points if getattr(p, "decision_date", None)]
    if not points:
        return {
            "status": "unavailable",
            "reason": "no_model_history",
            "decision_count": 0,
            "directional_accuracy": None,
            "mean_abs_error": None,
            "mean_signed_error": None,
            "dates": [],
        }

    dates: list[dict] = []
    correct = 0
    abs_errors: list[float] = []
    signed_errors: list[float] = []
    for point in points:
        predicted = float(getattr(point, "predicted_return", 0.0) or 0.0)
        actual = float(getattr(point, "actual_return", 0.0) or 0.0)
        is_correct = (predicted > 0) == (actual > 0)
        if is_correct:
            correct += 1
        abs_error = abs(predicted - actual)
        dates.append(
            {
                "date": point.decision_date,
                "predicted": predicted,
                "actual": actual,
                "correct": is_correct,
                "abs_error": abs_error,
            }
        )
        abs_errors.append(abs_error)
        signed_errors.append(predicted - actual)

    count = len(points)
    return {
        "status": "ok",
        "decision_count": count,
        "directional_accuracy": correct / count,
        "mean_abs_error": sum(abs_errors) / count,
        "mean_signed_error": sum(signed_errors) / count,
        "dates": dates,
    }
