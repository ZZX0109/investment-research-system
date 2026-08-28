"""§1 step-6 price-path runner.

Single entry point ``forecast(...)`` for the price-path prediction.  Routes
through the kittenCN temporal adapter when available; otherwise delegates to
the existing-model quantile projection (``build_price_path_projection``).  Both
paths return the same dict shape, so callers (snapshot builder + LLM tool) are
agnostic to which model produced the path.
"""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID


def forecast(
    symbol: str,
    model_readings: Mapping[str, Any] | None,
    latest_close: float | None,
    as_of: Any,
    realized_mae: float | None = None,
    task: str = "excess_return_240d",
    *,
    asset_id: str | UUID | None = None,
    repo: Any = None,
    project_root: Any = None,
    anchor_date: Any = None,
) -> dict[str, Any]:
    """§1 price-path forecast entry point.

    Tries the kittenCN temporal adapter first (the §1 row-5 temporal-port
    hook); when it is not vendored / not trained / torch unavailable it
    returns ``None`` and the runner degrades to the existing-model quantile
    projection — real data, never synthesized.
    """
    temporal = _try_kittencn_temporal(
        symbol,
        model_readings,
        latest_close,
        as_of,
        realized_mae,
        task,
        asset_id=asset_id,
        repo=repo,
        project_root=project_root,
        anchor_date=anchor_date,
    )
    if temporal is not None:
        return temporal

    # Default: the EXISTING trained long-term model's q10/q50/q90 fan.
    from investment_research.agent.evaluation import build_price_path_projection

    result = build_price_path_projection(
        model_readings,
        latest_close,
        anchor_date or as_of,
        realized_mae=realized_mae,
        task=task,
    )
    # §1 row-5 (训练说清楚): when the temporal model is NOT ready, surface the
    # honest partial-availability state (vendored_source ✓ / torch ✓ /
    # trained_weights ✗) so the LLM can cite "价格路径用 quantile 投影
    # （kittenCN 时序待训练：源已备、训练待日线+BERT）" — never a silent degrade.
    try:
        from investment_research.training.price_path.kittencn_adapter import prereq_status

        result["temporal_model_status"] = prereq_status()
    except Exception:
        pass
    return result


def _try_kittencn_temporal(
    symbol: str,
    model_readings: Mapping[str, Any] | None,
    latest_close: float | None,
    as_of: Any,
    realized_mae: float | None,
    task: str,
    *,
    asset_id: str | UUID | None,
    repo: Any = None,
    project_root: Any = None,
    anchor_date: Any = None,
) -> dict[str, Any] | None:
    """§1 row-5 kittenCN temporal hook.

    Returns a temporal-path dict when the kittenCN model is vendored at
    ``vendor/kittencn`` + trained + torch is available; otherwise ``None``
    (degrade to the quantile projection).  Every prerequisite miss is caught
    so the runner never crashes on a missing optional port.
    """
    if not symbol or latest_close is None:
        return None
    try:
        from investment_research.training.price_path.kittencn_adapter import forecast_temporal_path

        return forecast_temporal_path(
            symbol,
            model_readings,
            latest_close,
            as_of,
            realized_mae,
            task,
            asset_id=asset_id,
            repo=repo,
            project_root=project_root,
            anchor_close=latest_close,
            anchor_date=anchor_date or as_of,
        )
    except Exception:
        return None
